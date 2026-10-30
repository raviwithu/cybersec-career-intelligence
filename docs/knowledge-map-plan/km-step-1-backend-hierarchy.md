# Knowledge Map Step KM-1 — Placement Model and Published Hierarchy API

Read `00-shared-context.md` first. Backend only; no frontend changes in this step.

## Goal

Store which branch a topic belongs to in each domain, and serve the published map one level at a time.

## 1. Assessment (report before coding)

- Confirm the facts in shared context §2 against the code and the live/seeded database.
- List the active domains and their nesting, and how many published topics each has in `knowledge_topic_domains`.
- Check what `GET /api/v1/search` (`read_api.py`) returns today and whether it includes knowledge topics.
- Check whether `GET /api/v1/knowledge/topics/{topic_identifier}` returns relationships and level expectations.
- Record the baseline (shared context §5).

## 2. Migration

One additive migration chained from the current head:

- `knowledge_topic_domains.map_branch` — `String(20)`, nullable, check constraint
  `map_branch IN ('foundations','security','vulnerabilities')`.
- `knowledge_topic_domains.display_order` — `Integer`, not null, server default `0`.
- Index on `(domain_id, map_branch, display_order)`.
- Downgrade drops only these additions.

Update the `KnowledgeTopicDomain` model and add `MAP_BRANCHES` constants with display labels
("Foundations", "Security", "Common Vulnerabilities").

No data backfill. Existing rows stay `NULL` (not on the map).

## 3. Public endpoints (new module `knowledge_map_api.py` + `knowledge_map_service.py`)

All under `/api/v1/knowledge-map`, unauthenticated, published-only (topic `publication_status = 'published'`,
`is_active`, domain `is_active`). Responses contain node summaries only, never section content.

| Method & path | Returns |
|---|---|
| `GET /knowledge-map` | Root node and active top-level domains: `id, slug, name, child_domain_count, placed_topic_count` |
| `GET /knowledge-map/domains/{domain_id}/children` | Active child domains (same shape) **then** non-empty branch nodes `{domain_id, branch, label, topic_count}` |
| `GET /knowledge-map/domains/{domain_id}/branches/{branch}/topics?offset=&limit=` | Paginated topic nodes `{id, topic_key, name, short_description, placement_count, has_children}`, ordered by `display_order, name`; `limit` max 100, default 50 |
| `GET /knowledge-map/topics/{topic_identifier}/placements` | Every published path to the topic: `[{domain_path:[{id,name}], branch, label}]` (for breadcrumbs and cross-domain links) |
| `GET /knowledge-map/search?q=&limit=` | Matching topics (name, aliases, `topic_key`) with their placement paths, so the UI can reveal a node without expanding the whole tree. Min query length 2, max 100 chars |

Rules:
- `short_description` comes from the published `overview` section's `short_description`, falling back to
  `topic.description`, truncated to 200 characters.
- Unknown or inactive domain → 404. Invalid branch → 422. Topic with no published placement → empty list, not error.
- If `/search` already covers knowledge topics, have `/knowledge-map/search` reuse its matching logic instead of
  duplicating it. Do not change the existing `/search` response.
- Add `ETag` and `Cache-Control: public, max-age=60` on these responses. The ETag may be derived from the most recent
  `published_at` across topics and sections plus the placement count; it must change after any publish.
- Avoid N+1 queries: aggregate counts in SQL.

Do **not** add a topic-detail endpoint. The detail panel will reuse `GET /api/v1/knowledge/topics/{topic_identifier}`.
If that endpoint lacks `level_expectations`, add them as a new optional response field (backward compatible).

## 4. Temporary admin seeding helper (optional, test-only)

Do not add an admin write endpoint for placements in this step; writes arrive in Step KM-4 through proposals.
Tests create placements directly through the ORM.

## 5. Tests (`backend/tests/test_knowledge_map.py`)

1. Root returns only active top-level domains from taxonomy, in `display_order`.
2. A domain with child domains (Embedded Systems Security) returns the children first.
3. Branch nodes appear only when they have at least one published placement.
4. Foundations, Security and Common Vulnerabilities are scoped to their domain (a placement in domain A does not appear in domain B).
5. Draft, review-status and inactive topics are excluded everywhere, including counts and search.
6. One topic placed in two domains appears in both, with `placement_count = 2`, and stays a single `knowledge_topics` row.
7. Pagination, ordering, and the `limit` ceiling.
8. Search matches aliases and returns placement paths; short queries are rejected.
9. 404 / 422 cases.
10. ETag changes after a topic is published.
11. Migration upgrade and downgrade on SQLite.
12. Existing knowledge, career-readiness and taxonomy tests still pass unchanged.

## 6. Docs

Create `docs/knowledge-map.md` with: hierarchy rules (D1, D2), the Career Readiness side effect of placement,
and the endpoint contracts above with example responses.

## Out of scope

Frontend, proposals, publishing, content, AI.
