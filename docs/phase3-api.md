# Phase 3 REST API

## Architecture

The backend exposes read-only Phase 3 resources through a dedicated FastAPI router in `backend/app/read_api.py`. It uses SQLAlchemy 2 `select()` statements, dependency-injected `Session` objects, Pydantic response models in `backend/app/read_schemas.py`, and eager loading for nested associations. The existing Phase 2 reference-data write routes remain registered for backward compatibility; no new Phase 3 write routes were added.

All endpoints use the `/api/v1` prefix. FastAPI publishes interactive documentation at `/docs` and the OpenAPI schema at `/openapi.json`.

Response collections use a consistent pagination envelope:

```json
{
  "items": [],
  "meta": {"page": 1, "page_size": 25, "total": 0, "pages": 0}
}
```

`page_size` is limited to 100. Invalid query parameters return `422`; missing IDs return `404`; oversized requests return `413`; unexpected failures return a generic `500` response with a request ID while the internal exception is logged.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/domains` | Hierarchical domains and embedded subdomains. |
| GET | `/api/v1/domains/{id}` | One domain with its descendants. |
| GET | `/api/v1/levels` | Ordered Junior through Director levels and tracks. |
| GET | `/api/v1/categories` | All competency categories. |
| GET | `/api/v1/competencies` | Paginated competency list; filters: `category`, `domain`, `level`, `search`, `page`, `page_size`. |
| GET | `/api/v1/competencies/{id}` | Competency details, related competencies, domains, levels, and expectations. |
| GET | `/api/v1/expectations` | Paginated consolidated expectations; filters: `domain`, `level`, `category`, `importance`, `proficiency`, `page`, `page_size`. Legacy `domain_id` and `career_level_id` filters are also accepted. |
| GET | `/api/v1/expectations/{id}` | Expectation detail with supporting research references. |
| GET | `/api/v1/career-matrix` | Domain/level cells with expectation counts, competency counts, and category distributions. |
| GET | `/api/v1/compare` | Compare two to six levels within a domain using `domain` and comma-separated `levels`. |
| GET | `/api/v1/search` | Paginated search over domain, competency, and expectation text; filters: `keyword`, `domain`, `level`, `page`, `page_size`. |
| GET | `/api/v1/research-sources` | Paginated research references with associated expectation IDs. |

Domain filters include matching descendants. For example, filtering by `embedded-systems-security` includes expectations attached to Boot Security, Hardware Security, and the other embedded subdomains.

## Example requests

```bash
curl http://localhost:8100/api/v1/domains
curl 'http://localhost:8100/api/v1/competencies?domain=boot-security&level=architect&page=1&page_size=10'
curl 'http://localhost:8100/api/v1/expectations?domain=boot-security&importance=essential'
curl 'http://localhost:8100/api/v1/career-matrix'
curl 'http://localhost:8100/api/v1/compare?domain=boot-security&levels=senior,architect'
curl 'http://localhost:8100/api/v1/search?keyword=secure&domain=embedded-systems-security&page_size=10'
curl 'http://localhost:8100/api/v1/research-sources'
```

## Example response fragments

Competency list item:

```json
{
  "id": 12,
  "name": "Secure Boot",
  "slug": "secure-boot",
  "description": "Design and validate a trusted boot chain.",
  "category": {"id": 4, "name": "Security Architecture", "slug": "security-architecture"},
  "domains": [{"id": 8, "name": "Boot Security", "slug": "boot-security"}],
  "career_levels": [{"id": 5, "name": "Architect", "slug": "architect", "career_track": "technical"}]
}
```

Expectation detail:

```json
{
  "id": 31,
  "domain": {"id": 8, "name": "Boot Security", "slug": "boot-security"},
  "career_level": {"id": 5, "name": "Architect", "slug": "architect", "career_track": "technical"},
  "competency": {"id": 12, "name": "Secure Boot", "slug": "secure-boot"},
  "proficiency_level": "expert",
  "importance": "essential",
  "responsibility_type": "design",
  "experience_years_min": 7,
  "experience_years_max": null,
  "supporting_sources": []
}
```

## Observability and safety

- JSON-formatted request logs include request ID, method, path, status code, and duration.
- Responses include `X-Request-ID`.
- `MAX_REQUEST_BYTES` is configurable through environment settings and defaults to 1 MiB.
- CORS remains restricted to the configured frontend origins.
- SQLAlchemy expressions and bound parameters are used for user-provided filters; no SQL string interpolation is used.
- Database credentials remain environment-driven.
- No job/company models, job tracking, AI extraction, frontend changes, Ollama changes, or OpenWebUI changes were introduced.

## Known limitations and Phase 4 recommendations

- Search currently combines domain, competency, and expectation result sets in application memory before pagination. A future PostgreSQL full-text/trigram index can improve performance for larger datasets.
- Matrix and comparison responses are computed live from the current database and do not yet accept an analysis-version selector. Phase 4 should add version-aware snapshots once the research ingestion workflow is designed.
- Authentication, authorization, rate limiting, and administrative source-management APIs are intentionally deferred.
- Phase 4 should add production PostgreSQL query plans, indexes for common filter combinations, API contract generation checks, and deployment-level observability metrics.
