from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib import robotparser
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from .config import Settings
from .url_importer import PinnedBackend, UrlImportError, read_bounded, resolve_public_ips, validate_url

TRACKING_PARAMETERS = {"fbclid", "gclid", "dclid", "mc_cid", "mc_eid", "ref", "ref_"}
TRANSIENT_STATUSES = {408, 425, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class CollectedItem:
    title: str
    url: str
    content: str
    published_at: datetime | None = None
    metadata: dict[str, Any] | None = None


class CollectionError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False):
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(message)


def normalize_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.port is None and parsed.netloc.endswith(":"):
        raise ValueError("Only valid HTTP and HTTPS URLs without credentials or fragments are supported")
    query = [
        (key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_") and key.casefold() not in TRACKING_PARAMETERS
    ]
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc.casefold(), parsed.path or "/", urlencode(sorted(query)), ""))


def normalize_content(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _parse_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    return parsed


def _text(value: Any) -> str:
    if isinstance(value, str):
        return BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return "" if value is None else str(value)


def _field(item: dict[str, Any], path: str | None, default: Any = None) -> Any:
    if not path:
        return default
    current: Any = item
    for part in path.split("."):
        if not isinstance(current, dict):
            return default
        current = current.get(part)
    return current


class SecureResearchFetcher:
    def __init__(
        self,
        settings: Settings,
        *,
        client_factory: Callable[[str], httpx.Client] | None = None,
        resolver: Callable[[str, int], list[str]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.settings = settings
        self.client_factory = client_factory
        self.resolver = resolver or resolve_public_ips
        self.sleep = sleep

    def _client(self, destination_ip: str) -> httpx.Client:
        if self.client_factory is not None:
            return self.client_factory(destination_ip)
        transport = httpx.HTTPTransport(verify=True, trust_env=False, retries=0)
        transport._pool._network_backend = PinnedBackend(destination_ip)
        return httpx.Client(transport=transport, timeout=httpx.Timeout(self.settings.research_request_timeout_seconds), follow_redirects=False, trust_env=False)

    def _robots_allowed(self, url: str, destination_ip: str) -> bool:
        parsed = urlsplit(url)
        robots_url = urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))
        try:
            with self._client(destination_ip) as client:
                response = client.get(robots_url, headers={"User-Agent": "CyberSecCareerIntelligenceResearch/1.0"})
            if response.status_code in {401, 403}:
                return False
            if response.status_code >= 400:
                return True
            parser = robotparser.RobotFileParser(robots_url)
            parser.parse(response.text.splitlines())
            return parser.can_fetch("CyberSecCareerIntelligenceResearch", url)
        except (httpx.HTTPError, OSError, ValueError):
            return True

    def fetch(self, url: str, *, accept: str, respect_robots: bool = True, headers: dict[str, str] | None = None) -> tuple[bytes, str, int]:
        try:
            current_url = normalize_url(url)
        except (ValueError, UrlImportError) as exc:
            raise CollectionError("Source URL is invalid or blocked", status_code=400) from exc
        redirects = 0
        for _ in range(self.settings.url_import_max_redirects + 1):
            parsed = urlsplit(current_url)
            try:
                addresses = self.resolver(parsed.hostname or "", parsed.port or (443 if parsed.scheme == "https" else 80))
            except (UrlImportError, OSError, ValueError) as exc:
                raise CollectionError("Source hostname could not be resolved or is blocked", status_code=403) from exc
            if respect_robots and not self._robots_allowed(current_url, addresses[0]):
                raise CollectionError("The source robots policy does not permit this request", retryable=False)
            try:
                with self._client(addresses[0]) as client:
                    request_headers = {"Accept": accept, "User-Agent": getattr(self.settings, "research_allowed_user_agent", "CyberSecCareerIntelligenceResearch/1.0")}
                    request_headers.update(headers or {})
                    with client.stream("GET", current_url, headers=request_headers) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location or redirects >= self.settings.url_import_max_redirects:
                                raise CollectionError("The source exceeded the safe redirect limit", status_code=400)
                            current_url = normalize_url(urljoin(current_url, location))
                            redirects += 1
                            continue
                        if response.status_code >= 400:
                            raise CollectionError(
                                f"Source returned HTTP {response.status_code}",
                                status_code=response.status_code,
                                retryable=response.status_code in TRANSIENT_STATUSES,
                            )
                        content = read_bounded(response, self.settings.research_response_max_bytes)
                        return content, response.headers.get("content-type", "").split(";", 1)[0].casefold(), response.status_code
            except CollectionError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError, OSError) as exc:
                raise CollectionError("Source request failed", retryable=True) from exc
        raise CollectionError("The source exceeded the safe redirect limit", status_code=400)


def with_retries(fetch: Callable[[], Any], settings: Settings, sleep: Callable[[float], None] = time.sleep) -> Any:
    last_error: Exception | None = None
    for attempt in range(settings.research_retry_count + 1):
        try:
            return fetch()
        except CollectionError as exc:
            last_error = exc
            if not exc.retryable or attempt >= settings.research_retry_count:
                raise
            sleep(min(settings.research_retry_base_seconds * (2**attempt), 8))
    raise last_error or CollectionError("Source collection failed")


def extract_html_item(url: str, content: bytes) -> CollectedItem:
    soup = BeautifulSoup(content.decode("utf-8", errors="replace"), "html.parser")
    for node in soup.find_all(["script", "style", "noscript", "nav", "footer", "form"]):
        node.decompose()
    title_node = soup.find("h1") or soup.find("meta", attrs={"property": "og:title"}) or soup.find("title")
    title = (title_node.get("content") if title_node and title_node.name == "meta" else title_node.get_text(" ", strip=True) if title_node else "")[:300]
    body = soup.find("main") or soup.find("article") or soup.body or soup
    text = normalize_content(body.get_text(" ", strip=True))
    if not title or len(text) < 20:
        raise CollectionError("HTML source did not contain a usable title and research body", status_code=422)
    return CollectedItem(title=title, url=normalize_url(url), content=text, metadata={"extraction_method": "html"})


def _xml_value(element: ElementTree.Element, names: tuple[str, ...]) -> str:
    for child in list(element):
        local = child.tag.rsplit("}", 1)[-1].casefold()
        if local in names:
            if local == "link" and child.attrib.get("href"):
                return child.attrib["href"]
            return " ".join(child.itertext()).strip()
    return ""


def parse_feed(url: str, content: bytes) -> list[CollectedItem]:
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise CollectionError("RSS or Atom source returned invalid XML", status_code=422) from exc
    entries = [element for element in root.iter() if element.tag.rsplit("}", 1)[-1].casefold() in {"item", "entry"}]
    results = []
    for entry in entries:
        title = _xml_value(entry, ("title",))
        link = _xml_value(entry, ("link", "id")) or url
        description = _xml_value(entry, ("description", "summary", "content", "encoded"))
        if title and description:
            results.append(CollectedItem(title=title[:300], url=normalize_url(urljoin(url, link)), content=normalize_content(description), published_at=_parse_date(_xml_value(entry, ("pubdate", "published", "updated"))), metadata={"extraction_method": "feed"}))
    return results


class ResearchCollector:
    def __init__(self, settings: Settings, fetcher: SecureResearchFetcher | None = None):
        self.settings = settings
        self.fetcher = fetcher or SecureResearchFetcher(settings)

    def collect(self, source) -> list[CollectedItem]:
        config = source.configuration or {}
        respect_robots = bool(config.get("respect_robots", getattr(self.settings, "research_default_respect_robots", True)))
        if source.source_type == "public_api":
            body, content_type, _ = with_retries(lambda: self.fetcher.fetch(source.endpoint_url, accept="application/json", respect_robots=respect_robots), self.settings, self.fetcher.sleep)
            try:
                payload = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise CollectionError("Public API returned invalid JSON", status_code=422) from exc
            rows = _field(payload, config.get("items_path"), payload)
            if isinstance(rows, dict):
                rows = [rows]
            if not isinstance(rows, list):
                raise CollectionError("Configured API items_path did not identify a list", status_code=422)
            results = []
            for item in rows[: self.settings.research_max_items_per_run]:
                if not isinstance(item, dict):
                    continue
                title = _text(_field(item, config.get("title_field", "title"), "Untitled research"))[:300]
                url = _text(_field(item, config.get("url_field", "url"), source.endpoint_url))
                content = normalize_content(_text(_field(item, config.get("content_field", "description"), "")))
                if title and len(content) >= 20:
                    results.append(CollectedItem(title, normalize_url(url), content, _parse_date(_field(item, config.get("date_field", "published_at"))), {"extraction_method": "public_api", "content_type": content_type}))
            return results
        if source.source_type == "rss":
            body, _, _ = with_retries(lambda: self.fetcher.fetch(source.endpoint_url, accept="application/rss+xml,application/atom+xml,application/xml,text/xml", respect_robots=respect_robots), self.settings, self.fetcher.sleep)
            return parse_feed(source.endpoint_url, body)[: self.settings.research_max_items_per_run]
        urls = config.get("urls", [source.endpoint_url]) if source.source_type == "url_collection" else [source.endpoint_url]
        if not isinstance(urls, list) or not urls or len(urls) > 100:
            raise CollectionError("URL collection must contain between one and one hundred URLs", status_code=422)
        results = []
        for item_url in urls:
            body, content_type, _ = with_retries(lambda item_url=item_url: self.fetcher.fetch(item_url, accept="text/html,application/xhtml+xml,application/json", respect_robots=respect_robots), self.settings, self.fetcher.sleep)
            if "html" in content_type or not content_type:
                results.append(extract_html_item(item_url, body))
            elif "json" in content_type:
                payload = json.loads(body)
                results.append(CollectedItem(title=str(payload.get("title", "Research source"))[:300], url=normalize_url(item_url), content=normalize_content(_text(payload)), metadata={"extraction_method": "json"}))
        return results[: self.settings.research_max_items_per_run]
