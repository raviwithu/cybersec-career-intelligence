# Taxonomy Management

Phase 9 adds an administrator-managed taxonomy workspace at **Research Admin → Taxonomy Management**. It uses the existing `SecurityDomain`, `Industry`, `CareerLevel`, and `CompetencyCategory` entities; it does not create a parallel taxonomy system.

## Supported entries

- Security domains and hierarchical subdomains
- Industries and subindustries
- Career levels with `technical`, `management`, or `shared` tracks
- Competency categories

All managed entries have a canonical name and slug, description, display order, active status, and optional aliases. Active entries are used by public filters and new research classification. Inactive entries remain available to administrators and remain valid historical references.

## Administrator workflow

1. Open **Taxonomy Management** from the sidebar.
2. Enter the configured `ADMIN_API_KEY` when prompted.
3. Select a taxonomy tab, search by name/slug/alias, and use **Add** or **Edit**.
4. Use **Impact** before deactivation, merge, or deletion to review dependencies.
5. Prefer **Deactivate** for entries with published or historical references.
6. Use **Merge** only after reviewing the source, target, and affected record counts. A merge reassigns supported references in one transaction, retains the source as inactive, and records both sides in change history.
7. Review the **Change History** tab for actor, action, timestamp, and merge source/target information.

Aliases are normalized and unique within each taxonomy type. Context-sensitive aliases should be marked in the API payload when a label is not semantically safe without evidence.

## API

All mutation and management endpoints require `X-Admin-API-Key`.

- `GET /api/v1/research/taxonomy`
- `GET /api/v1/research/taxonomy/history`
- `GET /api/v1/research/taxonomy/{type}/{id}/impact`
- `POST /api/v1/research/taxonomy/{type}`
- `PATCH /api/v1/research/taxonomy/{type}/{id}`
- `POST /api/v1/research/taxonomy/{type}/{id}/merge`
- `POST /api/v1/research/taxonomy/{type}/{id}/deactivate`
- `POST /api/v1/research/taxonomy/{type}/{id}/reactivate`
- `DELETE /api/v1/research/taxonomy/{type}/{id}`

`type` is one of `domain`, `industry`, `career_level`, or `category`. Permanent deletion is permitted only when dependency counts are zero. The API blocks circular parents, duplicate names/slugs, conflicting aliases, stale updates, and merges into inactive targets.

Public catalog endpoints (`/domains`, `/levels`, `/categories`, `/industries`, and the knowledge taxonomy endpoint) return active values for new filters. Historical research and published expectations continue to resolve their stored IDs.

## AI and review integration

Research ingestion builds its extraction prompt from the current active database taxonomy, including descriptions and aliases. Model-generated slugs are resolved against that catalog; unknown terms remain unclassified and are not auto-created. Research Review filters and correction validation accept only active taxonomy IDs, while stored original AI classifications remain auditable.

## Database migration

Apply the Phase 9 migration with:

```bash
docker compose run --rm backend alembic upgrade head
```

Revision `ph9taxonomy` adds active flags and timestamps/order fields to existing tables, creates alias tables for domains, career levels, and categories, and creates `taxonomy_change_history`. Existing IDs and seeded rows are preserved. Industry aliases and activity fields continue using the existing industry tables.

## Deployment

The project Compose stack remains isolated under the project-specific `cybersec-career-intelligence-network` network and `cybersec-career-intelligence-postgres-data` volume. Start it with:

```bash
docker compose up -d --build
```

Keep `OLLAMA_BASE_URL=http://host.docker.internal:11434` in the project `.env`; Ollama is intentionally not defined as a Compose service. Set a strong project-local `ADMIN_API_KEY`, then run the migration before using taxonomy mutations. Do not expose the administrator key in frontend source or public logs.
