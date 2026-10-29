from __future__ import annotations

import hashlib
import imaplib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email import message_from_bytes
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .config import Settings
from .phase6_collectors import normalize_url

ALLOWED_SENDER = "jobalerts-noreply@linkedin.com"
LINKEDIN_HOSTS = {"linkedin.com", "www.linkedin.com", "lnkd.in"}
TRACKING_PARAMETERS = {"trk", "trackingid", "refid", "lipi", "midtoken", "midsig", "eid", "utm_source", "utm_medium", "utm_campaign", "fbclid", "gclid"}
JOB_PATH_PATTERN = re.compile(r"/jobs/(?:view|collections|search)/", re.I)
UNSAFE_TAGS = {"script", "style", "iframe", "object", "embed", "form", "noscript", "svg"}


class YahooMailError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False):
        self.retryable = retryable
        super().__init__(message)


@dataclass(frozen=True)
class MailMessage:
    uid: int
    uidvalidity: str
    raw: bytes


@dataclass(frozen=True)
class ParsedAlert:
    sender: str
    message_id: str | None
    subject: str
    received_at: datetime | None
    authentication_headers: dict[str, str]
    content_hash: str
    jobs: list[dict[str, Any]]


def decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except (UnicodeDecodeError, ValueError):
        return value.strip()


def normalized_sender(value: str | None) -> str:
    addresses = [(name, address.strip().casefold()) for name, address in getaddresses([value or ""]) if address.strip()]
    if len(addresses) != 1:
        return ""
    return addresses[0][1]


def canonical_job_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return None
        query = [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True) if key.casefold() not in TRACKING_PARAMETERS and not key.casefold().startswith("utm_")]
        return normalize_url(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), "")))
    except (ValueError, TypeError):
        return None


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _safe_html_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.find_all(UNSAFE_TAGS):
        node.decompose()
    for node in soup.find_all(["img", "source"]):
        node.decompose()
    return "\n".join(line for line in (_clean_text(value) for value in soup.get_text("\n").splitlines()) if line)


def _body_parts(message) -> tuple[str, str]:
    html_parts: list[str] = []
    text_parts: list[str] = []
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        if part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/html", "text/plain"}:
            continue
        payload = part.get_payload(decode=True) or b""
        charset = part.get_content_charset() or "utf-8"
        text = payload.decode(charset, errors="replace")
        if content_type == "text/html":
            html_parts.append(text)
        else:
            text_parts.append(text)
    return "\n".join(html_parts), "\n".join(text_parts)


def _job_url(url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold()
    return host in LINKEDIN_HOSTS and bool(JOB_PATH_PATTERN.search(parsed.path))


def _extract_card_jobs(html: str, plain: str, max_jobs: int) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    soup = BeautifulSoup(html, "html.parser") if html else None
    anchors = []
    if soup:
        for anchor in soup.find_all("a", href=True):
            url = canonical_job_url(anchor.get("href", ""))
            if url and _job_url(url):
                anchors.append((anchor, url))
    seen: set[str] = set()
    for anchor, url in anchors:
        if url in seen or len(jobs) >= max_jobs:
            continue
        card = anchor
        for parent in anchor.parents:
            text = _safe_html_text(str(parent))
            if len(text) >= 80 and len(text) <= 20_000:
                card = parent
                break
        card_text = _safe_html_text(str(card))
        title_node = card.find(["h1", "h2", "h3", "h4"]) if hasattr(card, "find") else None
        title = _clean_text(title_node.get_text(" ", strip=True) if title_node else anchor.get_text(" ", strip=True))
        if not title or title.casefold() in {"view job", "see job", "apply now", "learn more"}:
            continue
        lines = [line for line in card_text.splitlines() if line]
        employer = ""
        for line in lines:
            if line.casefold().startswith("at "):
                employer = line[3:].strip()
                break
        if not employer:
            company_node = card.find(class_=re.compile(r"company|employer|organization", re.I)) if hasattr(card, "find") else None
            employer = _clean_text(company_node.get_text(" ", strip=True) if company_node else "")
        location = ""
        location_node = card.find(class_=re.compile(r"location|place", re.I)) if hasattr(card, "find") else None
        if location_node:
            location = _clean_text(location_node.get_text(" ", strip=True))
        description = card_text
        jobs.append({"title": title[:300], "employer": employer[:300], "location": location[:300], "job_url": url, "description": description[:20_000], "description_complete": len(description) >= 240, "extraction_method": "linkedin_html_card"})
        seen.add(url)
    if len(jobs) < max_jobs:
        url_pattern = re.compile(r"https?://(?:www\.)?linkedin\.com/jobs/(?:view|collections|search)/[^\s<>\"']+", re.I)
        for match in url_pattern.findall(plain):
            url = canonical_job_url(match.rstrip(".,);"))
            if not url or url in seen or len(jobs) >= max_jobs:
                continue
            before = plain[:plain.find(match)].splitlines()
            title = _clean_text(before[-1] if before else "")
            if not title or len(title) > 300:
                title = "LinkedIn job alert listing"
            jobs.append({"title": title[:300], "employer": "", "location": "", "job_url": url, "description": "", "description_complete": False, "extraction_method": "linkedin_plain_text"})
            seen.add(url)
    return jobs


def parse_alert(raw: bytes, *, uid: int, uidvalidity: str, max_jobs: int = 50) -> ParsedAlert | None:
    message = message_from_bytes(raw)
    sender = normalized_sender(message.get("From"))
    if sender != ALLOWED_SENDER:
        return None
    subject = decode_header_value(message.get("Subject"))[:500]
    html, plain = _body_parts(message)
    safe_plain = _safe_html_text(html) if html else _safe_html_text(plain)
    jobs = _extract_card_jobs(html, safe_plain, max_jobs)
    if not jobs:
        return None
    received_at = None
    if message.get("Date"):
        try:
            received_at = parsedate_to_datetime(message.get("Date"))
            received_at = received_at if received_at.tzinfo else received_at.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError, IndexError):
            received_at = None
    auth_headers = {name: decode_header_value(message.get(name))[:1000] for name in ("Authentication-Results", "DKIM-Signature", "Received-SPF", "Return-Path") if message.get(name)}
    content_hash = hashlib.sha256(f"{sender}\n{subject}\n{message.get('Message-ID', '')}\n{safe_plain}".encode("utf-8")).hexdigest()
    return ParsedAlert(sender=sender, message_id=decode_header_value(message.get("Message-ID"))[:500] or None, subject=subject, received_at=received_at, authentication_headers=auth_headers, content_hash=content_hash, jobs=jobs)


class YahooImapClient:
    def __init__(self, settings: Settings, *, factory: Callable[..., Any] | None = None):
        self.settings = settings
        self.factory = factory or imaplib.IMAP4_SSL
        self.mail = None
        self.uidvalidity = ""

    def __enter__(self):
        try:
            self.mail = self.factory(self.settings.yahoo_imap_host, self.settings.yahoo_imap_port, timeout=self.settings.research_request_timeout_seconds)
        except (OSError, imaplib.IMAP4.error) as exc:
            raise YahooMailError("Yahoo IMAP TLS connection failed", retryable=True) from exc
        return self

    def login(self, email_address: str, app_password: str, folder: str) -> None:
        if self.mail is None:
            raise YahooMailError("Yahoo IMAP connection is not open")
        try:
            self.mail.login(email_address, app_password)
            status, _ = self.mail.select(folder, readonly=True)
            if status != "OK":
                raise YahooMailError(f"Yahoo mailbox folder '{folder}' could not be opened")
            response = self.mail.response("UIDVALIDITY") if hasattr(self.mail, "response") else ("OK", [b"1"])
            values = response[1] if response and len(response) > 1 else []
            self.uidvalidity = (values[0].decode() if values and isinstance(values[0], bytes) else str(values[0]) if values else "1")
        except (OSError, imaplib.IMAP4.error) as exc:
            raise YahooMailError("Yahoo authentication or mailbox selection failed") from exc

    def search_uids(self, *, date_from: datetime | None = None, date_to: datetime | None = None, minimum_uid: int = 0) -> list[int]:
        criteria = ["FROM", f'"{ALLOWED_SENDER}"']
        if date_from:
            criteria.extend(["SINCE", date_from.strftime("%d-%b-%Y")])
        if date_to:
            criteria.extend(["BEFORE", (date_to + timedelta(days=1)).strftime("%d-%b-%Y")])
        if minimum_uid:
            criteria.extend(["UID", f"{minimum_uid + 1}:*"])
        try:
            # Sender and date constraints are applied server-side before any body fetch.
            status, data = self.mail.search(None, *criteria)
            if status != "OK":
                raise YahooMailError("Yahoo IMAP search failed", retryable=True)
            raw_uids = data[0].split() if data and data[0] else []
            return [int(value) for value in raw_uids][: self.settings.mail_sync_max_messages]
        except (ValueError, OSError, imaplib.IMAP4.error) as exc:
            raise YahooMailError("Yahoo IMAP search failed", retryable=True) from exc

    def fetch_message(self, uid: int) -> MailMessage:
        try:
            if hasattr(self.mail, "uid"):
                status, data = self.mail.uid("FETCH", str(uid), "(BODY.PEEK[])")
            else:
                status, data = self.mail.fetch(str(uid), "(BODY.PEEK[])")
            raw = b"".join(part[1] for part in data if isinstance(part, tuple) and len(part) > 1 and isinstance(part[1], bytes))
            if status != "OK" or not raw:
                raise YahooMailError("Yahoo message could not be fetched")
            if len(raw) > self.settings.mail_max_message_bytes:
                raise YahooMailError("Yahoo message exceeded the configured size limit")
            return MailMessage(uid=uid, uidvalidity=self.uidvalidity, raw=raw)
        except (OSError, imaplib.IMAP4.error) as exc:
            raise YahooMailError("Yahoo message fetch failed", retryable=True) from exc

    def __exit__(self, *_):
        if self.mail is not None:
            try:
                self.mail.close()
            except (OSError, imaplib.IMAP4.error):
                pass
            try:
                self.mail.logout()
            except (OSError, imaplib.IMAP4.error):
                pass
        return False
