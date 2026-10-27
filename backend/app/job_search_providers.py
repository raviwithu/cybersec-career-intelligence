from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import json
from bs4 import BeautifulSoup

from .config import Settings
from .phase6_collectors import CollectionError, SecureResearchFetcher, normalize_content, normalize_url, with_retries

MIN_COMPLETE_DESCRIPTION_CHARS = 120


@dataclass(frozen=True)
class JobSearchCriteria:
    keywords: list[str]
    location: str
    experience_level: str
    date_posted: str
    employment_type: str
    work_mode: str
    max_results: int


@dataclass(frozen=True)
class JobSearchItem:
    title: str
    url: str
    description_url: str | None = None
    description: str | None = None
    snippet: str = ""
    location: str = ""
    external_id: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class JobSearchPage:
    items: list[JobSearchItem]
    total: int | None = None
    next_cursor: str | None = None


class JobSearchProvider(Protocol):
    provider_type: str

    def search(self, criteria: JobSearchCriteria, *, cursor: str | None = None, limit: int) -> JobSearchPage:
        ...

    def retrieve_description(self, item: JobSearchItem) -> str:
        ...


class JobSearchProviderUnavailable(CollectionError):
    def __init__(self, message: str):
        super().__init__(message, status_code=503, retryable=False)


def provider_statuses(settings: Settings) -> list[dict[str, Any]]:
    return [
        _status("linkedin_authorized", "Authorized LinkedIn integration", bool(settings.linkedin_authorized_api_base_url and settings.linkedin_authorized_api_key), [
            "Requires a permitted LinkedIn integration and credentials configured by the administrator.",
            "This application does not use undocumented LinkedIn APIs, scraping, CAPTCHA bypass, or authentication automation.",
        ]),
        _status("licensed_api", "Licensed job-data provider", bool(settings.licensed_job_provider_base_url and settings.licensed_job_provider_api_key), [
            "Requires a licensed provider endpoint and API key configured outside the database.",
        ]),
        _status("employer_ats", "Employer career page or ATS API", bool(settings.employer_ats_api_base_url), [
            "Supports only a configured public employer or ATS endpoint with a documented response contract.",
        ]),
        _status("import", "Permitted result URL or dataset import", True, [
            "Import does not claim live LinkedIn access; full descriptions still require permitted source URLs or complete exported descriptions.",
        ]),
    ]


def _status(provider_type: str, display_name: str, configured: bool, limitations: list[str]) -> dict[str, Any]:
    return {"provider_type": provider_type, "status": "configured" if configured else "unconfigured", "display_name": display_name, "limitations": limitations, "configured": configured}


class _HTTPJobSearchProvider:
    def __init__(self, provider_type: str, base_url: str, api_key: str | None, settings: Settings, fetcher: SecureResearchFetcher | None = None):
        self.provider_type = provider_type
        self.base_url = normalize_url(base_url)
        self.api_key = api_key
        self.settings = settings
        self.fetcher = fetcher or SecureResearchFetcher(settings)

    def search(self, criteria: JobSearchCriteria, *, cursor: str | None = None, limit: int) -> JobSearchPage:
        query = {
            "keywords": ",".join(criteria.keywords), "location": criteria.location,
            "experience_level": criteria.experience_level, "date_posted": criteria.date_posted,
            "employment_type": criteria.employment_type, "work_mode": criteria.work_mode,
            "limit": str(limit),
        }
        if cursor:
            query["cursor"] = cursor
        separator = "&" if "?" in self.base_url else "?"
        endpoint = self.base_url + separator + "&".join(f"{key}={_quote(value)}" for key, value in query.items() if value)
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body, _, _ = with_retries(lambda: self.fetcher.fetch(endpoint, accept="application/json", headers=headers), self.settings, self.fetcher.sleep)
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CollectionError("Job-search provider returned invalid JSON", status_code=422) from exc
        rows = payload.get("results", payload.get("items", [])) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise CollectionError("Job-search provider did not return a result list", status_code=422)
        items: list[JobSearchItem] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            url = _first(row, "url", "job_url", "link")
            title = _first(row, "title", "job_title", "name")
            if not url or not title:
                continue
            items.append(JobSearchItem(
                title=str(title)[:300], url=normalize_url(str(url)),
                description_url=_optional_url(_first(row, "description_url", "detail_url", "url")),
                description=_optional_text(_first(row, "description", "full_description", "body")),
                snippet=_optional_text(_first(row, "snippet", "summary"))[:20_000],
                location=_optional_text(_first(row, "location"))[:300],
                external_id=_optional_text(_first(row, "id", "external_id"))[:255] or None,
                metadata={"provider_type": self.provider_type, "provider_payload": {key: value for key, value in row.items() if key not in {"description", "full_description", "body"}}},
            ))
        total = payload.get("total") if isinstance(payload, dict) and isinstance(payload.get("total"), int) else None
        next_cursor = payload.get("next_cursor") if isinstance(payload, dict) else None
        return JobSearchPage(items=items, total=total, next_cursor=str(next_cursor) if next_cursor else None)

    def retrieve_description(self, item: JobSearchItem) -> str:
        if item.description and len(normalize_content(item.description)) >= MIN_COMPLETE_DESCRIPTION_CHARS:
            return normalize_content(item.description)
        target = item.description_url or item.url
        body, content_type, _ = with_retries(lambda: self.fetcher.fetch(target, accept="text/html,application/xhtml+xml", headers={}), self.settings, self.fetcher.sleep)
        if "html" not in content_type and content_type:
            raise CollectionError("The job description response was not HTML", status_code=422)
        soup = BeautifulSoup(body.decode("utf-8", errors="replace"), "html.parser")
        for node in soup.find_all(["script", "style", "noscript", "nav", "footer", "form"]):
            node.decompose()
        body_node = soup.find("main") or soup.find("article") or soup.body or soup
        text = normalize_content(body_node.get_text(" ", strip=True))
        if len(text) < MIN_COMPLETE_DESCRIPTION_CHARS:
            raise CollectionError("The full job description is incomplete or unavailable", status_code=422)
        return text


def _extract_complete_description(body: bytes) -> str:
    soup = BeautifulSoup(body.decode("utf-8", errors="replace"), "html.parser")
    for node in soup.find_all(["script", "style", "noscript", "nav", "footer", "form"]):
        node.decompose()
    body_node = soup.find("main") or soup.find("article") or soup.body or soup
    text = normalize_content(body_node.get_text(" ", strip=True))
    if len(text) < MIN_COMPLETE_DESCRIPTION_CHARS:
        raise CollectionError("The full job description is incomplete or unavailable", status_code=422)
    return text


class ImportJobSearchProvider:
    provider_type = "import"

    def __init__(self, settings: Settings, fetcher: SecureResearchFetcher | None = None):
        self.settings = settings
        self.fetcher = fetcher or SecureResearchFetcher(settings)

    def search(self, criteria: JobSearchCriteria, *, cursor: str | None = None, limit: int) -> JobSearchPage:
        raise JobSearchProviderUnavailable("Import provider does not perform live search; import permitted result URLs or an exported dataset")

    def retrieve_description(self, item: JobSearchItem) -> str:
        if item.description and len(normalize_content(item.description)) >= MIN_COMPLETE_DESCRIPTION_CHARS:
            return normalize_content(item.description)
        try:
            body, content_type, _ = with_retries(lambda: self.fetcher.fetch(item.description_url or item.url, accept="text/html,application/xhtml+xml", headers={}), self.settings, self.fetcher.sleep)
            if "html" not in content_type and content_type:
                raise CollectionError("The imported job description response was not HTML", status_code=422)
            return _extract_complete_description(body)
        except CollectionError as exc:
            raise CollectionError("Imported result has no accessible complete job description; manual review is required", status_code=422) from exc


def build_provider(provider_type: str, settings: Settings, *, fetcher: SecureResearchFetcher | None = None) -> JobSearchProvider:
    if provider_type == "import":
        return ImportJobSearchProvider(settings, fetcher)
    if provider_type == "linkedin_authorized":
        if not settings.linkedin_authorized_api_base_url or not settings.linkedin_authorized_api_key:
            raise JobSearchProviderUnavailable("No authorized LinkedIn provider is configured")
        return _HTTPJobSearchProvider(provider_type, settings.linkedin_authorized_api_base_url, settings.linkedin_authorized_api_key, settings, fetcher)
    if provider_type == "licensed_api":
        if not settings.licensed_job_provider_base_url or not settings.licensed_job_provider_api_key:
            raise JobSearchProviderUnavailable("No licensed job-data provider is configured")
        return _HTTPJobSearchProvider(provider_type, settings.licensed_job_provider_base_url, settings.licensed_job_provider_api_key, settings, fetcher)
    if provider_type == "employer_ats":
        if not settings.employer_ats_api_base_url:
            raise JobSearchProviderUnavailable("No employer or ATS provider is configured")
        return _HTTPJobSearchProvider(provider_type, settings.employer_ats_api_base_url, settings.employer_ats_api_key, settings, fetcher)
    raise JobSearchProviderUnavailable(f"Unsupported job-search provider: {provider_type}")


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if row.get(key) not in (None, ""):
            return row[key]
    return None


def _optional_text(value: Any) -> str:
    return "" if value is None else str(value)


def _optional_url(value: Any) -> str | None:
    if not value:
        return None
    try:
        return normalize_url(str(value))
    except ValueError as exc:
        raise CollectionError("Provider returned an invalid job URL", status_code=422) from exc


def _quote(value: str) -> str:
    from urllib.parse import quote_plus

    return quote_plus(value)
