# Security Knowledge Map

The Security Knowledge Map turns published knowledge topics into a tree that can be expanded one level at a time. The implementation plan is in [`knowledge-map-plan/`](knowledge-map-plan/README.md). This document describes what has shipped and is extended at each step.

| Step | Status |
|---|---|
| KM-1: placement model, published hierarchy API, search | Shipped |
| KM-2: map page, tree view, navigation, search UI | Not started |
| KM-3: topic detail panel | Not started |
| KM-4: map management, proposals, review, publish, rollback | Not started |
| KM-5: initial example topics, AI decomposition proposals | Not started |

## Hierarchy

```text
CyberSec Career Intelligence            (root)
└── Security Domain                     (active top-level security_domains)
    ├── Child Domain                    (active security_domains with parent_id)
    │   └── Branch → Topic
    └── Branch                          (Foundations | Security | Common Vulnerabilities)
        └── Topic                       (published, active knowledge_topics)
```

- **The map follows the existing taxonomy.** The root lists the active top-level domains in `display_order`. Expanding a domain shows its active child domains first, then its branches. Today only Embedded Systems Security has child domains. The map never creates, renames or restructures domains; use **Taxonomy Management** for that.
- **A domain is on the map only when it and every ancestor are active.** An active child under an inactive parent is hidden and returns 404.
- **Branches belong to one domain.** The Foundations branch of Web Application Security is unrelated to the Foundations branch of Cloud API Security. A branch node appears only when it holds at least one published topic.
- **Topics can be placed on any active domain**, including one with child domains. From KM-4, Knowledge Map Management will warn when you place a topic on a domain that has children.

## Placement

A placement is a row in the existing `knowledge_topic_domains` link table with a branch set. Migration `ph13mapplacement` adds two columns to that table:

| Column | Type | Meaning |
|---|---|---|
| `map_branch` | `String(20)`, nullable, `foundations`, `security` or `vulnerabilities` | The branch within that domain. `NULL` means the link is not on the map |
| `display_order` | `Integer`, default `0` | Order within the branch. Ties are ordered by topic name |

An index on `(domain_id, map_branch, display_order)` serves branch listings. The labels are defined once in `MAP_BRANCHES` (`backend/app/models.py`): Foundations, Security, Common Vulnerabilities.

Rules:

- **A topic has at most one branch per domain.** The `(topic_id, domain_id)` primary key enforces this.
- **A topic can be placed in many domains.** It stays a single `knowledge_topics` row, and `placement_count` reports how many published placements it has.
- **Existing links are not backfilled.** They keep `map_branch = NULL` and do not appear on the map until a placement is published.
- **Removing a placement sets `map_branch` back to `NULL`.** It never deletes the domain link.

> **Career Readiness side effect.** Career Readiness reads the same `knowledge_topic_domains` table. Placing a topic in a domain it was not linked to creates the link, so the topic also starts to appear for that domain in Career Readiness. Removing the placement leaves the link, and therefore the Career Readiness entry, in place.

Placements are written only by the publish step of a knowledge proposal (KM-4). There is no direct write endpoint.

## Public API

All endpoints are under `/api/v1/knowledge-map`, need no authentication, and return only published data. A topic must have `publication_status = 'published'` and `is_active`, and its domain and every ancestor domain must be active. Responses contain node summaries only, never section content. For topic detail, use the existing `GET /api/v1/knowledge/topics/{topic_identifier}`.

### Caching

Every response carries `Cache-Control: public, max-age=60` and an `ETag`. The ETag is derived from the latest topic and section publication and update times, the latest domain update, and every placement row. It changes after any publish, unpublish, placement change or domain edit. Send `If-None-Match` to receive `304 Not Modified` when nothing changed.

### `GET /knowledge-map`

Returns the root and the active top-level domains. `placed_topic_count` counts distinct published topics placed in the domain or in any of its active child domains.

```json
{
  "root": {"id": "root", "name": "CyberSec Career Intelligence"},
  "domains": [
    {"node_type": "domain", "id": 1, "slug": "web-application-security", "name": "Web Application Security", "child_domain_count": 0, "placed_topic_count": 4},
    {"node_type": "domain", "id": 5, "slug": "embedded-systems-security", "name": "Embedded Systems Security", "child_domain_count": 5, "placed_topic_count": 6}
  ]
}
```

### `GET /knowledge-map/domains/{domain_id}/children`

Returns the domain's active child domains (in the same shape as above), followed by its non-empty branches in the order Foundations, Security, Common Vulnerabilities. Returns 404 for an unknown domain, an inactive domain, or a domain under an inactive parent.

```json
{
  "domain": {"node_type": "domain", "id": 5, "slug": "embedded-systems-security", "name": "Embedded Systems Security", "child_domain_count": 5, "placed_topic_count": 6},
  "nodes": [
    {"node_type": "domain", "id": 8, "slug": "boot-security", "name": "Boot Security", "child_domain_count": 0, "placed_topic_count": 2},
    {"node_type": "branch", "domain_id": 5, "branch": "foundations", "label": "Foundations", "topic_count": 1}
  ]
}
```

### `GET /knowledge-map/domains/{domain_id}/branches/{branch}/topics?offset=0&limit=50`

Returns the topics in one branch of one domain, ordered by `display_order` and then name. `limit` defaults to 50 with a maximum of 100. An unknown or inactive domain returns 404; a branch other than `foundations`, `security` or `vulnerabilities` returns 422.

`short_description` is the published `overview` section's `short_description` when it has one, otherwise the topic `description`, cut to 200 characters. No topic has an `overview` section yet, so it currently always comes from `description`. `has_children` is true when the topic has a published, active child topic (`parent_topic_id`).

```json
{
  "domain_id": 8,
  "branch": "vulnerabilities",
  "label": "Common Vulnerabilities",
  "items": [
    {"id": 42, "topic_key": "rollback-attacks", "name": "Rollback Attacks", "short_description": "Forcing a device to boot an older, vulnerable firmware image.", "placement_count": 1, "has_children": false}
  ],
  "total": 1,
  "offset": 0,
  "limit": 50
}
```

### `GET /knowledge-map/topics/{topic_identifier}/placements`

`topic_identifier` is a topic id, `topic_key` or slug. Returns every published path to the topic, used for breadcrumbs and cross-domain links. A published topic with no placement returns `[]`. A topic that is unknown, unpublished or inactive returns 404.

```json
[
  {"domain_path": [{"id": 5, "name": "Embedded Systems Security"}, {"id": 8, "name": "Boot Security"}], "branch": "vulnerabilities", "label": "Common Vulnerabilities"},
  {"domain_path": [{"id": 4, "name": "Traditional Server Infrastructure Security"}], "branch": "security", "label": "Security"}
]
```

### `GET /knowledge-map/search?q=&limit=20`

Matches topic names, aliases and `topic_key` without regard to case. `q` must be 2 to 100 characters after trimming (otherwise 422), and `limit` defaults to 20 with a maximum of 50. `%` and `_` are matched literally. Names that start with the query are listed first. Only topics with at least one published placement are returned, because the map cannot reveal any other topic. Each result includes its placement paths, so the UI can expand straight to the node.

`GET /api/v1/search` does not cover knowledge topics, so this endpoint has its own matching. The existing `/search` response is unchanged.

```json
{
  "query": "rollback",
  "items": [
    {"id": 42, "topic_key": "rollback-attacks", "name": "Rollback Attacks", "short_description": "Forcing a device to boot an older, vulnerable firmware image.", "placements": [{"domain_path": [{"id": 5, "name": "Embedded Systems Security"}, {"id": 8, "name": "Boot Security"}], "branch": "vulnerabilities", "label": "Common Vulnerabilities"}]}
  ]
}
```

## Topic detail: career levels

`GET /api/v1/knowledge/topics/{topic_identifier}` (and the admin topic endpoints) now include an optional `level_expectations` list taken from `knowledge_topic_levels`. Older clients can ignore it. `expectation` is the knowledge expected at that level and `practical_capability` the practical skills. Only active career levels and active industries are included, ordered by career level `display_order`. Industry-agnostic rows come before industry-specific ones.

```json
"level_expectations": [
  {"career_level": {"id": 1, "name": "Junior", "slug": "junior", "career_track": "shared"}, "industry": null, "expectation": "Explains how a verified boot chain works.", "practical_capability": "Checks image signatures with vendor tools."}
]
```

## Code

| File | Purpose |
|---|---|
| `backend/migrations/versions/phase_13_knowledge_map_placement.py` | Migration `ph13mapplacement` |
| `backend/app/knowledge_map_api.py` | Routes, ETag and caching |
| `backend/app/knowledge_map_service.py` | Hierarchy, counts, placements, search, ETag |
| `backend/app/knowledge_map_schemas.py` | Response models |
| `backend/tests/test_knowledge_map.py` | Tests, including migration upgrade and downgrade |
