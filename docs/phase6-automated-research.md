# Phase 6: Automated Cybersecurity Research

Phase 6 collects approved external research, converts it into structured findings, and proposes changes to the existing Research Review workflow. It does not publish automated output directly.

## Operating model

1. An administrator registers a source in **Automated Research**.
2. The API validates the source type, HTTP(S) endpoint, URL collection, and configuration.
3. A manual run or `research-scheduler` worker selects enabled due sources.
4. Collection uses the RSS/Atom, public API, HTML, or URL-collection adapter.
5. Every endpoint is normalized, resolved, SSRF-checked, revalidated on redirects, and fetched with pinned transport, bounded response size, a redirect limit, and retry classification.
6. Extracted items are normalized and content-hashed. Identical content is skipped globally; a changed canonical URL creates a new version and change event.
7. A configured AI provider classifies content against the seeded domain, career-level, category, and industry taxonomy.
8. Provider/model, source URL, content version, evidence excerpt, and automation run are retained as provenance.
9. Automated findings are converted into existing `ResearchSubmission` / `ReviewChange` records and remain pending until an administrator reviews them.

## Source permissions and safety

Only explicitly approved sources should be registered. Phase 6 accepts:

- `public_api`: GET-only JSON endpoints with configured field paths.
- `rss`: RSS 2.0 or Atom feeds; linked article content is fetched only when configured.
- `html`: one permitted page or listing page, with optional CSS selectors.
- `url_collection`: up to 100 administrator-supplied HTTP(S) URLs.

Source configuration rejects credentials and secret-shaped fields. Literal loopback, private, link-local, reserved, and metadata IP destinations are rejected at registration. Hostnames are checked again at request time. Redirect targets are checked with the same controls, and requests are made through an IP-pinned transport while preserving the original host for TLS/HTTP behavior. Robots policy is enabled by default and can only be changed as an explicit source setting.

The collector bounds response bytes and redirects, uses a finite timeout, and retries only connection errors and transient HTTP statuses (`408`, `425`, `429`, `5xx`). Authentication, authorization, malformed URL, SSRF, and other permanent failures are not retried.

Automated source content is untrusted input. It is bounded before persistence and passed to the selected provider through the existing provider abstraction. Source content cannot publish knowledge or change taxonomy records by itself.

## Scheduling and Docker Compose

Compose starts a separate `research-scheduler` container for this project. It uses the same project-scoped `backend` image, PostgreSQL service, and Redis service; it does not create or start Ollama. Ollama remains on the Ubuntu host and is reached through `OLLAMA_BASE_URL` / `host.docker.internal`.

```bash
docker compose up --build
# The API and scheduler each run migrations through the backend entrypoint.
# The worker polls due schedules using RESEARCH_SCHEDULER_POLL_SECONDS.
```

The scheduler uses Redis key locks (`cybersec:research:source:<id>`) to avoid concurrent source collection. If Redis is unavailable, the worker uses a process-local lock as a safe degraded-mode fallback; multiple scheduler replicas should therefore be run only with Redis available.

Relevant settings:

| Setting | Purpose |
| --- | --- |
| `RESEARCH_SCHEDULER_ENABLED` | Enables scheduled collection in the worker. |
| `RESEARCH_SCHEDULER_POLL_SECONDS` | Worker poll interval. |
| `RESEARCH_REQUEST_TIMEOUT_SECONDS` | HTTP request timeout. |
| `RESEARCH_RESPONSE_MAX_BYTES` | Collector response limit. |
| `RESEARCH_RETRY_COUNT` | Maximum retry count for transient failures. |
| `RESEARCH_MAX_ITEMS_PER_RUN` | Per-source item limit. |
| `RESEARCH_LOCK_TTL_SECONDS` | Redis source lock TTL. |
| `RESEARCH_ALLOWED_USER_AGENT` | Collector User-Agent identifier. |
| `RESEARCH_DEFAULT_RESPECT_ROBOTS` | Default robots policy. |

## API

All Phase 6 routes require `X-Admin-API-Key`:

- `GET/POST /api/v1/research/automated/sources`
- `PATCH/DELETE /api/v1/research/automated/sources/{id}`
- `POST /api/v1/research/automated/sources/{id}/schedule`
- `POST /api/v1/research/automated/sources/{id}/pause`
- `POST /api/v1/research/automated/sources/{id}/resume`
- `GET /api/v1/research/automated/dashboard`
- `GET /api/v1/research/automated/runs`
- `POST /api/v1/research/automated/runs`
- `GET /api/v1/research/automated/runs/{id}`
- `GET /api/v1/research/automated/runs/{id}/attempts`
- `GET /api/v1/research/automated/coverage`
- `GET /api/v1/research/automated/changes`
- `GET /api/v1/research/automated/findings`
- `GET /api/v1/research/automated/status`

The OpenAPI document at `/docs` is authoritative for request and response schemas.

## LinkedIn Job Search integration

Automated Research includes **LinkedIn Job Search** saved criteria for keywords, location, experience level, date posted, employment type, work mode, maximum results, and daily/weekly/manual scheduling. Searches are stored as criteria and temporary processing records only; the feature does not create permanent job or company tracking.

Provider modes are explicit:

- `linkedin_authorized`: available only when an officially authorized integration is configured through `LINKEDIN_AUTHORIZED_API_BASE_URL` and `LINKEDIN_AUTHORIZED_API_KEY`. The application does not use undocumented LinkedIn APIs, authentication bypass, CAPTCHA circumvention, or scraping. Without both settings, the UI reports **unconfigured** and no live search is attempted.
- `licensed_api`: a licensed job-data provider with a documented JSON search contract and credentials configured outside the database.
- `employer_ats`: a configured public employer career page or supported ATS endpoint.
- `import`: always available for permitted result URLs or exported result datasets. Search snippets are never treated as complete job descriptions.

For a configured provider, pagination continues until the saved-search limit is reached or the provider has no next cursor. Each run records the provider-reported total separately from retrieved, unique, queued, description-retrieved, analyzed, duplicate, manual-review, and failed counts. Duplicate URLs/external IDs are removed before queueing; content fingerprints and the existing Phase 6 content-version system catch unchanged or cross-source content.

Every unique result is processed individually. A complete description is fetched from the permitted detail URL or supplied dataset; short snippets are marked `manual_review_required`. Complete content is normalized, fingerprinted, passed through the selected Ollama/OpenWebUI model, classified against security domain × career level × industry, and sent through the existing Research Review proposal flow. No result automatically publishes knowledge.

Job-search endpoints are administrator-authenticated under `/api/v1/research/automated/job-searches`. The UI provides saved searches, provider status, Search Jobs, Schedule Search, import, run history, actual progress counts, result URLs, failures, and retry of eligible results. Search executions use per-search locks and the existing scheduler. Temporary runs/results are retained for `JOB_SEARCH_RETENTION_DAYS` (default 90); saved criteria remain.

Relevant environment settings:

| Setting | Purpose |
| --- | --- |
| `LINKEDIN_AUTHORIZED_API_BASE_URL` / `LINKEDIN_AUTHORIZED_API_KEY` | Optional permitted LinkedIn integration; empty means unconfigured. |
| `LICENSED_JOB_PROVIDER_BASE_URL` / `LICENSED_JOB_PROVIDER_API_KEY` | Optional licensed provider endpoint and credential. |
| `EMPLOYER_ATS_API_BASE_URL` / `EMPLOYER_ATS_API_KEY` | Optional documented employer/ATS endpoint and credential. |
| `JOB_SEARCH_RETENTION_DAYS` | Retention period for temporary search runs and results. |


## Coverage semantics

Coverage is computed across industry × security domain × career level cells. It is evidence coverage, not a ranking of competency importance. A cell is:

- **none**: no automated evidence.
- **limited**: at least one finding.
- **adequate**: at least three findings from at least two sources.

The response includes counts and the threshold values so consumers do not mistake absent evidence for absence of a competency.

## Review and change detection

A content digest identifies unchanged content. New content creates a version and an automated analysis. Changed content creates a `ResearchChangeEvent` with a summary and `ReviewChange` proposal. Findings are represented through the same draft/pending review records used by manual research. Administrators can edit, approve, reject, and publish through Research Review; automated content is not granted a bypass.

## Known limitations

- The Phase 6 adapter supports GET-only public APIs; authenticated/private API credentials are intentionally not stored in source configuration.
- HTML extraction is bounded and selector-based but is not a browser renderer; JavaScript-only pages are not guaranteed to produce content.
- Robots retrieval failures fail open for availability, while a successfully parsed disallow rule is honored.
- Hostnames are checked at fetch time, but DNS infrastructure and destination ownership can change after collection; provenance preserves the resolved request context where available.
- The dashboard describes evidence found by this pipeline and does not claim complete market coverage.
