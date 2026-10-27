from __future__ import annotations

import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx
from bs4 import BeautifulSoup
from httpcore._backends.sync import SyncBackend

from .config import Settings

REDIRECT_STATUSES = {301, 302, 303, 307, 308}
CONTENT_TYPES = {"text/html", "application/xhtml+xml"}
UNSAFE_ELEMENT_NAMES = {"aside", "footer", "form", "header", "iframe", "nav", "noscript", "script", "style"}
# Match whole class/id tokens only: a bare substring match on "ad" also removed
# containers such as "mx-details-container-padding" (LinkedIn's job description).
UNSAFE_ATTRIBUTE_PATTERN = re.compile(r"(?<![a-z0-9])(?:ads?|advert\w*|breadcrumbs?|cookies?|footer|header|menu|nav|navbar|navigation|social|share)(?![a-z0-9])", re.I)
DESCRIPTION_CLASS_PATTERN = re.compile(r"description", re.I)
MIN_DESCRIPTION_CHARS = 200


class UrlImportError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class ImportedJob:
    source_url: str
    job_title: str
    job_description: str
    extraction_method: str
    date_posted: str | None = None


class PinnedBackend(SyncBackend):
    """Connect to the already-validated IP while retaining URL TLS/SNI."""

    def __init__(self, destination_ip: str):
        super().__init__()
        self.destination_ip = destination_ip

    def connect_tcp(self, host: str, port: int, timeout: float | None = None, local_address: str | None = None, socket_options=None) -> httpcore.NetworkStream:
        return super().connect_tcp(self.destination_ip, port, timeout, local_address, socket_options)


class UrlImporter:
    def __init__(
        self,
        settings: Settings,
        client_factory: Callable[[str], httpx.Client] | None = None,
        resolver: Callable[[str, int], list[str]] | None = None,
    ):
        self.settings = settings
        self.client_factory = client_factory or self._real_client
        self.resolver = resolver or resolve_public_ips

    def import_job(self, url: str) -> ImportedJob:
        current_url = validate_url(url, resolver=self.resolver)
        for redirect_count in range(self.settings.url_import_max_redirects + 1):
            parts = urlsplit(current_url)
            destination_ips = self.resolver(parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80))
            if not destination_ips:
                raise UrlImportError("dns_failure", "The job page hostname could not be resolved.", 400)
            destination_ip = destination_ips[0]
            try:
                with self.client_factory(destination_ip) as client:
                    with client.stream("GET", current_url, headers={"Accept": "text/html,application/xhtml+xml", "User-Agent": "CyberSecCareerIntelligenceResearch/1.0"}) as response:
                        if response.status_code in REDIRECT_STATUSES:
                            location = response.headers.get("location")
                            if not location:
                                raise UrlImportError("extraction_failed", "The job page returned an invalid redirect.", 502)
                            if redirect_count >= self.settings.url_import_max_redirects:
                                raise UrlImportError("redirect_limit", "The job page exceeded the safe redirect limit.", 400)
                            current_url = validate_url(urljoin(current_url, location), resolver=self.resolver)
                            continue
                        if response.status_code == 403:
                            raise UrlImportError("access_denied", "The job page denied access (HTTP 403). Paste the description manually.", 403)
                        if response.status_code == 404:
                            raise UrlImportError("not_found", "The job posting was not found (HTTP 404).", 404)
                        if response.status_code == 429:
                            raise UrlImportError("rate_limited", "The job page rate-limited this request (HTTP 429). Try again later or paste the description.", 429)
                        if response.status_code >= 400:
                            raise UrlImportError("fetch_failed", f"The job page could not be fetched (HTTP {response.status_code}).", 502)
                        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                        if content_type not in CONTENT_TYPES:
                            raise UrlImportError("unsupported_content_type", "The URL did not return an HTML job page.", 415)
                        content = read_bounded(response, self.settings.url_import_max_bytes)
                imported = extract_job(current_url, content, self.settings.max_research_bytes)
                return imported
            except UrlImportError:
                raise
            except httpx.TimeoutException as exc:
                raise UrlImportError("timeout", "The job page timed out while fetching. Paste the description manually.", 408) from exc
            except httpx.HTTPError as exc:
                raise UrlImportError("network_error", "The job page could not be reached. Paste the description manually.", 502) from exc
            except OSError as exc:
                raise UrlImportError("network_error", "The job page could not be reached. Paste the description manually.", 502) from exc
        raise UrlImportError("redirect_limit", "The job page exceeded the safe redirect limit.", 400)

    def _real_client(self, destination_ip: str) -> httpx.Client:
        transport = httpx.HTTPTransport(verify=True, trust_env=False, retries=0)
        # HTTPX 0.28 exposes no public network-backend parameter. The pinned
        # httpcore pool lets us retain the validated IP through the connection.
        transport._pool._network_backend = PinnedBackend(destination_ip)
        return httpx.Client(transport=transport, timeout=httpx.Timeout(self.settings.url_import_timeout_seconds), follow_redirects=False, trust_env=False)


def validate_url(value: str, resolver: Callable[[str, int], list[str]] | None = None) -> str:
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as exc:
        raise UrlImportError("invalid_url", "Enter a valid HTTP or HTTPS job posting URL.", 400) from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or port is None and parsed.netloc.endswith(":"):
        raise UrlImportError("invalid_url", "Only valid HTTP and HTTPS job posting URLs are supported.", 400)
    addresses = (resolver or resolve_public_ips)(parsed.hostname, port or (443 if parsed.scheme == "https" else 80))
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise UrlImportError("blocked_destination", "Private, local, link-local, reserved, and metadata destinations are blocked.", 403)
    return parsed.geturl()


def resolve_public_ips(hostname: str, port: int) -> list[str]:
    try:
        literal = ipaddress.ip_address(hostname)
        addresses = [str(literal)]
    except ValueError:
        try:
            records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise UrlImportError("dns_failure", "The job page hostname could not be resolved.", 400) from exc
        addresses = list(dict.fromkeys(str(record[4][0]) for record in records))
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise UrlImportError("blocked_destination", "Private, local, link-local, reserved, and metadata destinations are blocked.", 403)
    return addresses


def read_bounded(response: httpx.Response, max_bytes: int) -> bytes:
    content_length = response.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > max_bytes:
        raise UrlImportError("response_too_large", "The job page response exceeds the permitted size.", 413)
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes(64 * 1024):
        total += len(chunk)
        if total > max_bytes:
            raise UrlImportError("response_too_large", "The job page response exceeds the permitted size.", 413)
        chunks.append(chunk)
    return b"".join(chunks)


def extract_job(source_url: str, content: bytes, max_description_bytes: int) -> ImportedJob:
    try:
        html = content.decode("utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
    except Exception as exc:
        raise UrlImportError("extraction_failed", "The job page HTML could not be parsed.", 422) from exc
    structured = extract_json_ld(soup)
    if structured:
        title, description, date_posted = structured
        if len(description.encode("utf-8")) > max_description_bytes:
            raise UrlImportError("description_too_large", "The extracted job description exceeds the permitted size.", 413)
        return ImportedJob(source_url, title, description, "json_ld", date_posted)
    title, description = extract_html(soup)
    if not title:
        raise UrlImportError("missing_title", "The job page did not contain a usable job title.", 422)
    if not description:
        raise UrlImportError("missing_description", "The job page did not contain a usable job description. Paste it manually.", 422)
    if len(description.encode("utf-8")) > max_description_bytes:
        raise UrlImportError("description_too_large", "The extracted job description exceeds the permitted size.", 413)
    return ImportedJob(source_url, title, description, "html")


def extract_json_ld(soup: BeautifulSoup) -> tuple[str, str, str | None] | None:
    for script in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        try:
            payload = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        for item in _json_ld_items(payload):
            types = item.get("@type", [])
            types = types if isinstance(types, list) else [types]
            if not any(str(value).casefold() == "jobposting" for value in types):
                continue
            title = clean_text(item.get("title") or item.get("jobTitle"))
            description = html_to_text(item.get("description"))
            if title and description:
                date_posted = clean_text(item.get("datePosted")) or None
                return title, description, date_posted
    return None


def _json_ld_items(payload: Any):
    if isinstance(payload, list):
        for item in payload:
            yield from _json_ld_items(item)
    elif isinstance(payload, dict):
        if "@graph" in payload:
            yield from _json_ld_items(payload["@graph"])
        yield payload


def extract_html(soup: BeautifulSoup) -> tuple[str, str]:
    title_node = soup.find("h1") or soup.find("meta", attrs={"property": "og:title"}) or soup.find("title")
    title = clean_text(title_node.get("content") if title_node and title_node.name == "meta" else title_node.get_text(" ", strip=True) if title_node else "")
    for node in soup.find_all(UNSAFE_ELEMENT_NAMES):
        node.decompose()
    for node in soup.find_all(["h1", "title"]):
        node.decompose()
    for node in soup.find_all(attrs={"class": UNSAFE_ATTRIBUTE_PATTERN}):
        node.decompose()
    for node in soup.find_all(attrs={"id": UNSAFE_ATTRIBUTE_PATTERN}):
        node.decompose()
    candidates = [soup.find("main"), soup.find("article"), soup.find(attrs={"role": "main"})]
    candidates.extend(soup.find_all(attrs={"class": re.compile(r"(?:job|posting|description|content|career|position|role)", re.I)}))
    candidates = [candidate for candidate in candidates if candidate is not None]
    # Prefer an explicit job-description container over the whole <main>, which on
    # sites like LinkedIn also holds sign-in prompts and related-job listings.
    described = [
        candidate for candidate in candidates
        if DESCRIPTION_CLASS_PATTERN.search(" ".join(candidate.get("class") or []))
        and len(candidate.get_text(" ", strip=True)) >= MIN_DESCRIPTION_CHARS
    ]
    content_node = max(described or candidates, key=lambda node: len(node.get_text(" ", strip=True)), default=soup.body or soup)
    return title, html_to_text(str(content_node))


def html_to_text(value: Any) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(str(value), "html.parser")
    for node in soup.find_all(UNSAFE_ELEMENT_NAMES):
        node.decompose()
    lines = [re.sub(r"\s+", " ", line).strip() for line in soup.get_text("\n").splitlines()]
    return "\n".join(line for line in lines if line)


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()
