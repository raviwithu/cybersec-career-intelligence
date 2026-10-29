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
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .config import Settings
from .phase6_collectors import normalize_url

ALLOWED_SENDER = "jobalerts-noreply@linkedin.com"
LINKEDIN_HOSTS = {"linkedin.com", "www.linkedin.com"}
# Alert links look like /comm/jobs/view/<id>/ or /jobs/view/<slug>-<id>/; search-result and alert-management links are not jobs.
LINKEDIN_JOB_PATH = re.compile(r"^(?:/comm)?/jobs/view/(?:[^/]*-)?(\d+)/?$", re.I)
PLAIN_JOB_LINK = re.compile(r"https?://(?:www\.)?linkedin\.com/(?:comm/)?jobs/view/[^\s<>\"']+", re.I)
GENERIC_LINK_TEXT = {"view job", "see job", "apply now", "learn more"}
WORK_MODE_PATTERN = re.compile(r"\s*\((on-site|remote|hybrid)\)\s*", re.I)
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


def linkedin_job_id(value: str) -> str | None:
    try:
        parsed = urlsplit(value.strip())
    except (ValueError, TypeError, AttributeError):
        return None
    if parsed.scheme.casefold() not in {"http", "https"} or (parsed.hostname or "").casefold() not in LINKEDIN_HOSTS:
        return None
    match = LINKEDIN_JOB_PATH.match(parsed.path)
    return match.group(1) if match else None


def canonical_job_url(value: str) -> str | None:
    # LinkedIn alert links carry per-link tracking and one-click sign-in tokens (otpToken), so keep only the job ID.
    job_id = linkedin_job_id(value)
    if job_id:
        return f"https://www.linkedin.com/jobs/view/{job_id}"
    try:
        parsed = urlsplit(value.strip())
        return normalize_url(urlunsplit((parsed.scheme.casefold(), parsed.netloc, parsed.path, parsed.query, "")))
    except (ValueError, TypeError, AttributeError):
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
        try:
            text = payload.decode(charset, errors="replace")
        except LookupError:
            text = payload.decode("utf-8", errors="replace")
        if content_type == "text/html":
            html_parts.append(text)
        else:
            text_parts.append(text)
    return "\n".join(html_parts), "\n".join(text_parts)


def _lines(node) -> list[str]:
    return [line for line in (_clean_text(value) for value in node.get_text("\n").splitlines()) if line]


def _card_for(anchor, job_id: str):
    # Widen to the largest ancestor whose links all point at this job, so headers and neighbouring cards stay out.
    card = anchor
    for parent in anchor.parents:
        if parent.name in {"body", "html", "[document]"}:
            break
        if any(linkedin_job_id(link["href"]) != job_id for link in parent.find_all("a", href=True)):
            break
        card = parent
    return card


def _split_company_line(line: str) -> tuple[str, str, str]:
    employer, _, location = line.partition(" · ")
    work_mode = ""
    match = WORK_MODE_PATTERN.search(location)
    if match:
        work_mode = match.group(1).capitalize()
        location = WORK_MODE_PATTERN.sub(" ", location)
    return _clean_text(employer), _clean_text(location), work_mode


def _job(title: str, employer: str, location: str, work_mode: str, url: str, lines: list[str], method: str) -> dict[str, Any]:
    # Alert emails only carry a card summary; full descriptions are retrieved separately before approval.
    return {"title": title[:300], "employer": employer[:300], "location": location[:300], "work_mode": work_mode[:40], "job_url": url, "description": "\n".join(lines)[:20_000], "description_complete": False, "extraction_method": method}


def _html_jobs(html: str, max_jobs: int) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.find_all(UNSAFE_TAGS):
        node.decompose()
    by_job: dict[str, list[Any]] = {}
    for anchor in soup.find_all("a", href=True):
        job_id = linkedin_job_id(anchor["href"])
        if job_id:
            by_job.setdefault(job_id, []).append(anchor)
    jobs: list[dict[str, Any]] = []
    for job_id, anchors in by_job.items():
        if len(jobs) >= max_jobs:
            break
        card = _card_for(anchors[0], job_id)
        lines = _lines(card)
        heading = card.find(["h1", "h2", "h3", "h4"])
        texts = sorted((text for text in (_clean_text(anchor.get_text(" ", strip=True)) for anchor in anchors) if text and text.casefold() not in GENERIC_LINK_TEXT), key=len)
        title = _clean_text(heading.get_text(" ", strip=True)) if heading else texts[0] if texts else lines[0] if lines else ""
        if not title:
            continue
        rest = lines[lines.index(title) + 1:] if title in lines else lines
        company_line = next((line for line in rest if " · " in line), None)
        if company_line:
            employer, location, work_mode = _split_company_line(company_line)
        else:
            employer, location, work_mode = (rest[0] if rest else ""), "", ""
        jobs.append(_job(title, employer, location, work_mode, f"https://www.linkedin.com/jobs/view/{job_id}", lines, "linkedin_html_card"))
    return jobs


def _plain_jobs(plain: str, seen: set[str], max_jobs: int) -> list[dict[str, Any]]:
    # Plain-text alerts separate cards with dashed rules: title, employer and location lines, then "View job: <url>".
    jobs: list[dict[str, Any]] = []
    for block in re.split(r"\n\s*-{10,}\s*\n", plain):
        if len(jobs) >= max_jobs:
            break
        match = PLAIN_JOB_LINK.search(block)
        url = canonical_job_url(match.group(0).rstrip(".,);")) if match else None
        if not url or url in seen:
            continue
        lines = [line for line in (_clean_text(value) for value in block[:match.start()].splitlines()) if line]
        lines = [line for line in lines if not line.casefold().startswith(("your job alert for", "view job"))]
        if not lines:
            continue
        employer, location, work_mode = _split_company_line(lines[1]) if len(lines) > 1 and " · " in lines[1] else ((lines[1] if len(lines) > 1 else ""), (lines[2] if len(lines) > 2 else ""), "")
        jobs.append(_job(lines[0], employer, location, work_mode, url, lines, "linkedin_plain_text"))
        seen.add(url)
    return jobs


def _extract_jobs(html: str, plain: str, max_jobs: int) -> list[dict[str, Any]]:
    jobs = _html_jobs(html, max_jobs) if html else []
    jobs += _plain_jobs(plain, {job["job_url"] for job in jobs}, max_jobs - len(jobs))
    return jobs


def parse_alert(raw: bytes, *, uid: int, uidvalidity: str, max_jobs: int = 50) -> ParsedAlert | None:
    message = message_from_bytes(raw)
    sender = normalized_sender(message.get("From"))
    if sender != ALLOWED_SENDER:
        return None
    subject = decode_header_value(message.get("Subject"))[:500]
    html, plain = _body_parts(message)
    safe_plain = _safe_html_text(html) if html else _safe_html_text(plain)
    jobs = _extract_jobs(html, plain, max_jobs)
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
            # Sender and date constraints are applied server-side before any body fetch. UID SEARCH returns stable UIDs;
            # plain SEARCH would return sequence numbers, which shift on expunge and do not match UID FETCH.
            status, data = self.mail.uid("SEARCH", None, *criteria)
            if status != "OK":
                raise YahooMailError("Yahoo IMAP search failed", retryable=True)
            raw_uids = data[0].split() if data and data[0] else []
            return [int(value) for value in raw_uids][: self.settings.mail_sync_max_messages]
        except (ValueError, OSError, imaplib.IMAP4.error) as exc:
            raise YahooMailError("Yahoo IMAP search failed", retryable=True) from exc

    def fetch_message(self, uid: int) -> MailMessage:
        try:
            status, size_data = self.mail.uid("FETCH", str(uid), "(RFC822.SIZE)")
            size = re.search(rb"RFC822\.SIZE (\d+)", b" ".join(part if isinstance(part, bytes) else part[0] for part in size_data or [] if part))
            if status == "OK" and size and int(size.group(1)) > self.settings.mail_max_message_bytes:
                raise YahooMailError("Yahoo message exceeded the configured size limit")
            status, data = self.mail.uid("FETCH", str(uid), "(BODY.PEEK[])")
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
