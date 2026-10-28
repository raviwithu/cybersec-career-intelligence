from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Protocol
from urllib.parse import urlencode

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
    country: str = "us"
    max_pages: int = 3


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
    country: str = ""
    employment_type: str = ""
    posted_at: datetime | None = None


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
        _status("jsearch", "JSearch via RapidAPI", bool(getattr(settings, "jsearch_api_key", None)), [
            "Uses the official JSearch RapidAPI search and job-details endpoints.",
            "Request, page, result, retry, and rate-limit budgets are bounded by backend settings.",
        ]),
        _status("employer_ats", "Employer career page or ATS API", bool(settings.employer_ats_api_base_url), [
            "Supports only a configured public employer or ATS endpoint with a documented response contract.",
        ]),
        _status("import", "Permitted result URL or dataset import", True, [
            "Import does not claim live LinkedIn access; full descriptions still require permitted source URLs or complete exported descriptions.",
        ]),
    ]


class JSearchProvider:
    provider_type = "jsearch"

    def __init__(self, settings: Settings, fetcher: SecureResearchFetcher | None = None):
        self.settings = settings
        self.fetcher = fetcher or SecureResearchFetcher(settings)
        self.stats = SimpleNamespace(api_requests=0, pages_requested=0, rate_limit_errors=0, quota_errors=0)

    @property
    def configured(self) -> bool:
        return bool(self.settings.jsearch_api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "X-RapidAPI-Key": self.settings.jsearch_api_key or "",
            "X-RapidAPI-Host": self.settings.jsearch_api_host,
        }

    def _request_json(self, endpoint: str, params: dict[str, str]) -> dict[str, Any]:
        if not self.configured:
            raise CollectionError("JSearch provider is not configured", status_code=503, retryable=False)
        if self.stats.api_requests >= self.settings.jsearch_max_requests_per_run:
            self.stats.quota_errors += 1
            raise CollectionError("JSearch request budget exhausted for this run", status_code=429, retryable=False)
        query = urlencode({key: value for key, value in params.items() if value not in (None, "")})
        target = f"{endpoint}{'&' if '?' in endpoint else '?'}{query}"
        last_error: CollectionError | None = None
        for attempt in range(max(0, self.settings.jsearch_retry_count) + 1):
            if self.stats.api_requests >= self.settings.jsearch_max_requests_per_run:
                self.stats.quota_errors += 1
                raise CollectionError("JSearch request budget exhausted for this run", status_code=429, retryable=False)
            self.stats.api_requests += 1
            try:
                body, _, _ = self.fetcher.fetch(
                    target,
                    accept="application/json",
                    respect_robots=False,
                    headers=self._headers(),
                    timeout_seconds=self.settings.jsearch_timeout_seconds,
                )
                payload = json.loads(body)
                if not isinstance(payload, dict):
                    raise CollectionError("JSearch returned an invalid response", status_code=422)
                if str(payload.get("status", "SUCCESS")).upper() not in {"SUCCESS", "OK"}:
                    raise CollectionError("JSearch rejected the request", status_code=422)
                return payload
            except CollectionError as exc:
                last_error = exc
                if exc.status_code in {401, 403}:
                    self.stats.quota_errors += 1
                    raise CollectionError("JSearch authentication or subscription access failed", status_code=exc.status_code) from exc
                if exc.status_code == 429:
                    self.stats.rate_limit_errors += 1
                    if attempt >= self.settings.jsearch_retry_count:
                        raise CollectionError("JSearch rate limit reached; retry the run later", status_code=429, retryable=True) from exc
                    self.fetcher.sleep(max(self.settings.jsearch_rate_limit_sleep_seconds, self.settings.jsearch_retry_base_seconds * (2**attempt)))
                    continue
                if not exc.retryable or attempt >= self.settings.jsearch_retry_count:
                    raise CollectionError("JSearch request failed", status_code=exc.status_code, retryable=exc.retryable) from exc
                self.fetcher.sleep(min(self.settings.jsearch_retry_base_seconds * (2**attempt), 8))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise CollectionError("JSearch returned invalid JSON", status_code=422) from exc
        raise last_error or CollectionError("JSearch request failed")

    def search(self, criteria: JobSearchCriteria, *, cursor: str | None = None, limit: int) -> JobSearchPage:
        # Cursor is "<page>" (legacy /search) or "<page>:<api cursor>" (/search-v2).
        page_text, _, api_cursor = (cursor or "").partition(":")
        page = int(page_text) if page_text.isdigit() else 1
        query = " ".join(criteria.keywords)
        if criteria.location:
            query = f"{query} in {criteria.location}"
        params = {
            "query": query,
            "page": "" if api_cursor else str(page),
            "cursor": api_cursor,
            "num_pages": "1",
            "country": criteria.country,
            "date_posted": {"any": "all", "24h": "today"}.get(criteria.date_posted, criteria.date_posted),
            "employment_types": criteria.employment_type.upper(),
            "remote_jobs": "true" if criteria.work_mode == "remote" else "",
        }
        payload = self._request_json(self.settings.jsearch_api_endpoint, params)
        self.stats.pages_requested += 1
        data = payload.get("data", [])
        next_api_cursor = None
        if isinstance(data, dict):
            rows = data.get("jobs", [])
            next_api_cursor = data.get("cursor") if isinstance(data.get("cursor"), str) else None
        else:
            rows = data
        if not isinstance(rows, list):
            raise CollectionError("JSearch response did not contain a data list", status_code=422)
        items = [item for row in rows if isinstance(row, dict) for item in [self._item(row, criteria.country)] if item is not None]
        next_cursor = None
        if items and page < min(criteria.max_pages, self.settings.jsearch_max_pages_per_run):
            if isinstance(data, dict):
                next_cursor = f"{page + 1}:{next_api_cursor}" if next_api_cursor else None
            else:
                next_cursor = str(page + 1)
        total = payload.get("estimated_total") or payload.get("total")
        return JobSearchPage(items=items[:limit], total=int(total) if isinstance(total, int) else None, next_cursor=next_cursor)

    def retrieve_description(self, item: JobSearchItem) -> str:
        if item.description and len(normalize_content(BeautifulSoup(item.description, "html.parser").get_text(" ", strip=True))) >= MIN_COMPLETE_DESCRIPTION_CHARS:
            return normalize_content(BeautifulSoup(item.description, "html.parser").get_text(" ", strip=True))
        if item.external_id:
            payload = self._request_json(self.settings.jsearch_job_details_endpoint, {"job_id": item.external_id, "country": item.country or "us"})
            rows = payload.get("data", [])
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                description = rows[0].get("job_description")
                if isinstance(description, str) and len(normalize_content(BeautifulSoup(description, "html.parser").get_text(" ", strip=True))) >= MIN_COMPLETE_DESCRIPTION_CHARS:
                    return normalize_content(BeautifulSoup(description, "html.parser").get_text(" ", strip=True))
        raise CollectionError("JSearch returned only a partial or unavailable job description; manual review is required", status_code=422)

    def test_connection(self) -> JobSearchPage:
        return self.search(JobSearchCriteria(["cybersecurity"], "", "", "all", "", "any", 1, "us", 1), limit=1)

    @staticmethod
    def _item(row: dict[str, Any], default_country: str) -> JobSearchItem | None:
        title = row.get("job_title")
        url = row.get("job_apply_link") or row.get("job_google_link")
        if not isinstance(title, str) or not title.strip() or not isinstance(url, str) or not url.strip():
            return None
        try:
            canonical_url = normalize_url(url)
        except ValueError:
            return None
        description = row.get("job_description") if isinstance(row.get("job_description"), str) else None
        city = row.get("job_city") or ""
        state = row.get("job_state") or ""
        country = row.get("job_country") or default_country
        location = row.get("job_location") or ", ".join(str(value) for value in (city, state, country) if value)
        metadata_keys = (
            "job_publisher", "employer_name", "employer_website", "job_is_remote", "job_highlights",
            "job_required_skills", "job_required_education", "job_experience_required", "job_experience_in_place_of_work",
            "job_onet_soc", "job_onet_job_zone", "job_occupational_categories", "job_salary", "job_min_salary", "job_max_salary",
        )
        metadata = {"provider_type": "jsearch", **{key: row[key] for key in metadata_keys if key in row and row[key] is not None}}
        posted = row.get("job_posted_at_datetime_utc") or row.get("job_posted_at_datetime")
        posted_at = None
        if isinstance(posted, str):
            try:
                posted_at = datetime.fromisoformat(posted.replace("Z", "+00:00"))
            except ValueError:
                pass
        return JobSearchItem(
            title=title[:300], url=canonical_url, description_url=canonical_url, description=description,
            snippet=(description or "")[:20_000], location=str(location)[:300], external_id=str(row.get("job_id")) if row.get("job_id") else None,
            metadata=metadata, country=str(country)[:2].casefold(), employment_type=str(row.get("job_employment_type") or "")[:80], posted_at=posted_at,
        )




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
    if provider_type == "jsearch":
        if not settings.jsearch_api_key:
            raise JobSearchProviderUnavailable("No JSearch API key is configured")
        return JSearchProvider(settings, fetcher)
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
