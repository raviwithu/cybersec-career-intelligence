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

## Map interface

The **Security Knowledge Map** page is in the sidebar under **Explore**, after Knowledge Base (view id `knowledge-map`). It reads only the public endpoints above, so it shows published placements only.

### Interactions

- The map opens with the root and the active top-level domains. Expanding a node fetches its children once and keeps them in page state; collapsing hides them without discarding them.
- Expanding a domain shows its child domains first, then its non-empty branches. A domain with nothing below it shows "No published topics yet".
- Branch topics load 50 at a time. A "Load more (N remaining)" node fetches the next page.
- Toolbar: Expand, Collapse, Expand children (opens one level below the selection, loading each child on demand, never the whole map), Collapse all, Go to parent, and for the graph view Zoom in, Zoom out, Fit, Reset view and four pan buttons.
- Search is debounced (300 ms, at least 2 characters) and uses `/knowledge-map/search`. Choosing a result expands only the nodes on that result's path and selects the topic; nothing else is expanded or collapsed. A result with several placements asks which path to show. A topic beyond the loaded pages is added to its branch so it can be revealed without loading every page.
- The breadcrumb shows the selected node's path; each crumb selects that node.
- Selecting a topic opens the topic detail panel (see "Topic detail panel" below). On desktop the panel widens while a topic is selected.
- Deep links: `#knowledge-map?topic=<topic_key>` opens the map at the topic's first placement. The page keeps the URL in step with the selected topic using `history.replaceState`, so selection does not add history entries.
- Graph / List switches views. Both share the same expansion and selection. The choice is stored in `localStorage` (`cybersec-career-intelligence.knowledge-map-view`); without a stored choice, screens up to 800 px wide start in List.
- Failures: if the root fails, the page shows the shared error component with Try again. If a node's children fail, a "Could not load. Retry" node appears in its place.

### Visual design

Node types are root, domain, child domain, branch, topic, plus "load more", empty and error placeholders. Domains take an accent from a six-colour category palette; child domains inherit their parent's. Branches are blue (Foundations, ▤), green (Security, ◆) and red (Common Vulnerabilities, ⚠), always with their text label and icon so colour is never the only signal. The selected node has a white border and a focus-colour ring. Colours are CSS variables on `.knowledge-map-page`; the dark values match the app, and light values are defined under `:root[data-theme="light"]` for when the app gains a light theme (it has none today). At 800 px and narrower, the details panel becomes a bottom drawer with a close button. `prefers-reduced-motion` turns off viewport animations (zoom, fit, centring) and the drawer transition.

### Accessibility

- List view is a WAI-ARIA tree: `tree`, nested `treeitem` and `group`, with `aria-level`, `aria-posinset`, `aria-setsize`, `aria-expanded` (expandable nodes only) and `aria-selected`. One row is tabbable at a time. Keys: Up/Down move, Right expands or moves to the first child, Left collapses or moves to the parent, Home/End jump, Enter selects (or loads more / retries), Space expands or collapses.
- Graph view: every toolbar control is a button reachable with Tab. Each graph node is a button; Enter selects it and Space expands or collapses it. Pan buttons and centring on search, breadcrumb and parent selections mean nothing requires drag-to-pan.

### Loading and performance

- `KnowledgeMapPage` is loaded with `React.lazy`, and inside it the graph (`@xyflow/react` 12.12.0, `d3-hierarchy` 3.1.2, pinned) is a second lazy chunk, so other pages and the List view never download the graph library. Build sizes at KM-2: main bundle 439.23 kB (119.69 kB gzip, +1.95 kB over KM-1), map page 24.6 kB (8.9 kB gzip), graph 187.1 kB (61.0 kB gzip) plus 15.9 kB CSS. At KM-3: main bundle 450.87 kB (123.56 kB gzip; the shared section renderers and diagram wrapper load with the Knowledge Base page), map page 29.9 kB (10.6 kB gzip), `@xyflow/react` shared chunk 184.8 kB (60.1 kB gzip), diagram canvas 2.2 kB, syntax highlighter 86.5 kB (26.9 kB gzip, loaded only when code is shown).
- Layout uses `d3-hierarchy` `tree()` left to right over the visible nodes only. It is memoised on structure (nodes, children, expansion, loading state), so changing the selection never re-runs it. The tidy-tree layout is recomputed for all visible nodes when children load, not just the expanded subtree, because adding children shifts siblings; with 1,005 visible nodes it takes about 1 ms.
- The graph renders only nodes inside the viewport (`onlyRenderVisibleElements`).
- Measured in the Vitest/jsdom test with a 1,000-topic branch loaded 50 at a time: the slowest page load and render took 71 ms, and selecting a topic with all 1,000 listed took 59 ms. A real browser is usually faster than jsdom.

## Topic detail panel

`KnowledgeMapTopicPanel.jsx` shows the selected topic from `GET /api/v1/knowledge/topics/{topic_identifier}`. The header has the name, the path, every placement (each one reveals that path), a "Mapped in N domains" badge and "Open full topic page", which opens the existing Knowledge Base topic view.

Tabs appear only when the topic has published content for them, so foundational topics without vulnerability content simply have fewer tabs. Tabs follow the WAI-ARIA tabs pattern (Left/Right, Home/End).

| Tab | Source |
|---|---|
| Overview | `overview`: short description first; the technical explanation sits behind "Show technical details" |
| How It Works | `how_it_works` steps and diagram; a Vulnerable / Secure toggle when `architecture` has diagrams of both variants |
| Example Code | `code_examples`: vulnerable and secure code side by side when there is room, stacked otherwise; explanation and security control below |
| Attack Surface | `attack_surfaces` |
| Mitigations | `mitigations` |
| Real-World CVEs | `real_world_examples` |
| Architecture | `architecture` diagrams |
| Career Levels | `level_expectations` (from `knowledge_topic_levels`) |
| Related Topics | `related_topics`, grouped by display label; clicking one moves the map to that topic |
| References | `references`, with provenance and verification status |

The section renderers live in `KnowledgeSections.jsx` and are shared with the Knowledge Base topic page (`KnowledgeTopicPage.jsx`), which also gained the Example Code and Architecture tabs and now draws `how_it_works` diagrams instead of printing their JSON.

- **Code**: `prism-react-renderer` 2.4.1 (pinned) turns code into React text tokens; code is never evaluated or inserted as HTML. It has no grammar for Java, C#, PHP, Ruby, Bash or HTTP, so those use the generic C-like grammar or plain text. Panes are labelled "⚠ Vulnerable" and "✓ Secure" in text as well as colour, each with a Copy button. The highlighter is a lazy chunk; plain text shows while it loads.
- **Diagrams**: `KnowledgeDiagram.jsx` checks the diagram again (nodes, unique ids, edges pointing at existing nodes) and shows "A diagram could not be displayed because the definition is invalid." instead of anything it cannot draw. The canvas (`KnowledgeDiagramCanvas.jsx`, read-only `@xyflow/react`, lazy) uses `knowledgeDiagramLayout.js`: sequence diagrams as one lane per node with one row per message in edge order; other kinds as a left-to-right layered layout where each trust boundary gets its own band and is drawn as a labelled dashed region. Every diagram has a "Text version of this diagram" listing the steps in edge order and the boundary membership; it starts open when the user prefers reduced motion.
- **Real-World CVEs**: identifier, advisory title, affected product (`affected_product` or legacy `affected_component`), description (`description` or legacy `vulnerability_mechanism`), weakness (`weakness` or `cwe`), impact, remediation, reference, verification status and exploitation status. "Exploited in the wild" appears only when `exploitation_status` is `exploited_in_the_wild` and `verification_status` is `verified` or `authoritative`; otherwise the label is "Proof of concept" (when that is the status) or "Publicly disclosed". Anything not verified or authoritative carries an "Unverified" badge. An empty section shows "No verified real-world example has been added."
- **Career levels**: the level selector lists the active career levels from `/api/v1/levels`, grouped Shared, Technical, Management. The chosen level shows Knowledge (`expectation`) and Practical Skills (`practical_capability`) separately, with industry-specific rows labelled. A level with no row shows "No expectations defined for this level yet."; no other level's text is reused. When a topic has no level rows but has the legacy `career_level_guidance` section, that section is shown read-only instead.
- **Links**: only http(s) URLs become links, always `target="_blank"` with `rel="noopener noreferrer"`; the URL appears on hover and keyboard focus. Other URLs are not rendered.

## Content model

Both new section types are part of `SECTION_TYPES` and go through the knowledge contract like every other section (`ADD_SECTION`, `UPDATE_SECTION`, and `ADD_DIAGRAM` for diagrams). Their content is validated by strict Pydantic models in `backend/app/knowledge_content_schemas.py` when a proposal is created, when a reviewer modifies it, and again on publish. Unknown keys are rejected. The existing `_clean_value` (which rejects `<script>`, `<iframe>`, `<object>`, `<embed>`) and http(s)-only URL checks still apply. Coverage counts only the seven original sections, because code examples and architecture diagrams are optional for a topic; adding them did not change any topic's coverage.

### `code_examples`

```json
{"items": [{
  "title": "Order lookup",
  "language": "python",
  "vulnerable": "…",
  "secure": "…",
  "explanation": "…",
  "security_control": "Object-level authorization"
}]}
```

- `language`: one of python, javascript, typescript, java, go, csharp, c, cpp, rust, php, ruby, http, json, yaml, bash.
- At most 6 items. `vulnerable`, `secure` and `explanation` at most 8,000 characters each; an item needs `vulnerable` or `secure`.
- Only whole-section actions are accepted (`ADD_SECTION`, `UPDATE_SECTION`); item-append actions such as `ADD_MITIGATION` are rejected for this section.

### `architecture` and the diagram schema

```json
{"diagrams": [{
  "kind": "architecture | sequence | trust_boundary | attack_path | flow",
  "title": "…",
  "variant": "vulnerable | secure | neutral",
  "nodes": [{"id": "api", "label": "API", "type": "actor | service | datastore | control | external", "boundary": "internet"}],
  "edges": [{"from": "user", "to": "api", "label": "GET /orders/1002", "order": 1}],
  "boundaries": [{"id": "internet", "label": "Internet"}]
}]}
```

- Ids match `^[a-z0-9_-]{1,40}$` and are unique. Labels and titles are plain text (no `<` or `>`), at most 120 characters.
- At most 40 nodes, 80 edges and 20 boundaries per diagram, and 12 diagrams per section. Edges must reference existing nodes; a node's `boundary` must reference a declared boundary.
- No style, colour or URL fields exist; any extra key is rejected.
- Defaults: `kind` flow, `variant` neutral, node `type` service, empty `title`.
- `ADD_DIAGRAM` with section `architecture` appends one diagram (`{"diagram": {...}}` or the bare diagram); with `how_it_works` it replaces that section's single `diagram`, as before.
- The same schema validates `how_it_works.diagram` on write. On read, the public topic endpoint drops a stored diagram that no longer validates instead of failing: `how_it_works` gets `diagram: null` and `diagram_hidden: true`; `architecture` keeps the valid diagrams and reports `hidden_diagram_count`; `code_examples` reports `hidden_item_count`. The admin endpoint returns stored content unchanged.

### Relationship types

Stored types for topic relationships (`knowledge_topic_relationships`, created through `ADD_TOPIC_RELATIONSHIP` proposals): `prerequisite`, `related`, `specialization`, `dependency`, `mitigated_by`, `tested_by`. Other types and self-relationships are rejected when the proposal is created, modified or published.

`related_topics` in the topic response now lists both directions, each with `direction` (`outgoing` or `incoming`) and a display `label`. Inverse labels are never stored.

| Type | Outgoing label | Incoming label |
|---|---|---|
| `prerequisite` | Prerequisite | Prerequisite for |
| `related` | Related | Related |
| `specialization` | Specialization | Generalises |
| `dependency` | Depends on | Used by |
| `mitigated_by` | Mitigated by | Protects against |
| `tested_by` | Tested by | Tests |

The competency relationship validator in `knowledge_schemas.py` (and its `ck_relationship_type` database constraint) belongs to competencies, not knowledge topics, and is unchanged.

### Career-level source

Career-level content comes from `knowledge_topic_levels` (`level_expectations` in the topic response); level lists come from the active `career_levels` rows grouped by `career_track`, never a hardcoded list. The legacy `career_level_guidance` section is shown only when a topic has no level rows. The Knowledge Base section editor now builds that section's default keys from `/api/v1/levels`, so Guide and Supervisor are included; saved content is loaded as it was stored.

## Admin and review workflow

Map changes never write live tables directly (D3). Every change is a knowledge-contract proposal: created with `POST /api/v1/knowledge/proposals`, reviewed with the existing review endpoint (approve, modify, reject, defer), and written to live tables only by an explicit publish (`POST /api/v1/knowledge/admin/proposals/{id}/publish`). Approval never changes live data.

**Knowledge Map Management** (`KnowledgeMapAdminPage.jsx`, Administration › Knowledge Map Management, view `knowledge-map-admin`, admin key required):

- Browses the map with the KM-2 components in an admin mode. Topics and branches with open map proposals (draft, review, deferred, approved) carry an amber "Pending" badge with text. Pending state comes from the proposal queue, never from live data, and the public map never receives the admin mode, so it never shows these badges.
- Selecting a node opens forms that create proposals:
  - **Topic:** place, move, remove placement, set parent, add relationship, remove relationship, career levels (one level and optional industry at a time), deactivate (optionally "duplicate of" another topic), restore version, and "Edit sections".
  - **Branch:** reorder with ↑/↓ buttons, or place a topic there.
  - **Domain:** place a topic there.
- "Edit sections" opens `KnowledgeSectionEditor`, which now has structured editors for `code_examples` (form fields per example) and `architecture` (per-diagram JSON with live validation and a rendered preview).
- Placing on a domain that has child domains shows a warning (D1). Domains are edited only in Taxonomy Management, which the page links to.
- New topic: as you type, the form lists possible duplicates: exact matches by normalised name, slug, key or alias, plus similar names. It refuses exact matches, and the backend enforces the same rule. A new topic can carry one placement.
- Every form requires a change reason.

**Knowledge Review › Mind Map Changes** (`KnowledgeReviewPage.jsx`): a tab next to "All proposals". It lists the map actions, plus `CREATE_TOPIC` proposals that include placements (`GET /knowledge/admin/proposals?group=map`).

- **Header:** each proposal shows action, source type, status, submitter, change reason and the existing evidence view.
- **Before and after:** a line diff of the captured live state (−) against the proposed change (+), and the affected branches before and after publish from the map-preview endpoint.
- **Controls:** the existing Approve, Modify, Defer and Reject controls, then a separate Publish step for approved proposals.
- **Merge:** the existing merge action is refused for map actions, because moving a placement onto another topic is not meaningful. To retire a duplicate, deactivate it with "duplicate of".

### Action payloads

All actions use the existing proposal envelope (`schema_version`, `source_type`, `topic_id` or `topic_key`, `action`, `proposed_content`, `change_reason`, `references`). `change_reason` is required for every map action. Payloads are strict: unknown keys are rejected.

| Action | `proposed_content` | Publish effect |
|---|---|---|
| `PLACE_TOPIC` | `{"domain_id": 2, "map_branch": "security", "display_order": 3}` (`display_order` optional) | Creates the domain link if missing, sets the branch; without an order the topic goes last in the branch |
| `UNPLACE_TOPIC` | `{"domain_id": 2}` | `map_branch = NULL`; the domain link stays |
| `MOVE_TOPIC` | `{"from": {"domain_id": 2}, "to": {"domain_id": 5, "map_branch": "foundations", "display_order": null}}` | Unplace and place in one transaction (also moves between branches of one domain) |
| `REORDER_TOPICS` | `{"domain_id": 2, "map_branch": "security", "ordered_topic_ids": [7, 1, 9]}` | Rewrites `display_order` 0..n for that branch; the list must match the published topics in the branch exactly |
| `SET_PARENT_TOPIC` | `{"parent_topic_id": 12}` or `{"parent_topic_id": null}` | Updates `parent_topic_id`; self-parenting and cycles are rejected at create, modify and publish |
| `REMOVE_TOPIC_RELATIONSHIP` | `{"target_topic_id": 7, "relationship_type": "tested_by"}` | Deletes that relationship row (it must exist) |
| `DEACTIVATE_TOPIC` | `{"reason": "Duplicate of JSON Web Tokens (topic 7)."}` | `is_active = false`; the topic leaves the map and the Knowledge Base |
| `UPDATE_CAREER_LEVELS` | `{"levels": [{"career_level_id": 1, "industry_id": null, "expectation": "…", "practical_capability": "…"}]}` | Upserts the listed `knowledge_topic_levels` rows; other rows are untouched |
| `RESTORE_VERSION` | `{"target": "section", "section_type": "overview", "version": 2}` or `{"target": "topic", "version": 5}` | Republishes the stored snapshot as a new version (see Rollback) |
| `CREATE_TOPIC` | existing payload plus optional `"placements": [{"domain_id": 2, "map_branch": "foundations"}]` | Creates the topic and its placements in one transaction |

Rules:

- **Validation:** checked at create, again when a reviewer modifies a proposal, and again at publish, because the map may have changed. Domains must be active with active ancestors. The topic must exist and be active (except for `RESTORE_VERSION`), and branches must be valid.
- **Duplicates:** `CREATE_TOPIC` is rejected with 409 when an existing topic matches the normalised name, slug, `topic_key` or an alias (a match on the new topic's aliases counts too). The response is `{"detail": {"message", "existing_topic_id", "existing_topic_key"}}` and suggests `PLACE_TOPIC` or a section update instead. The check runs again at publish.
- **Captured state:** `original_content` records the live state the change touches. Examples are `{"placement": …}`, `{"from": …, "to": …}`, `{"members": [...]}`, `{"parent_topic_id": …}` and `{"levels": [...]}`. Review shows it as the "before".
- **Backward compatibility:** `UPDATE_CAREER_LEVEL_GUIDANCE` still writes the legacy `career_level_guidance` section, as before. Every other existing action behaves as before.

### Preview

`GET /api/v1/knowledge/admin/proposals/{id}/map-preview` (admin) returns `{proposal_id, action, status, branches: [{domain_id, domain_name, map_branch, label, before: [{topic_id, name}], after: [...]}], message}`.

- **How it works:** it applies the proposal to live data inside the request's transaction using the same code as publish, reads the affected branches, and always rolls back. Nothing is written.
- **Message:** `message` explains when there is nothing to show. That covers proposals that change no branch (parent, relationships, levels, section restore), proposals that are no longer unpublished, and proposals that no longer apply to the current map.

## Publication and versioning

- **One transaction:** publish runs in a single transaction. It locks the topic and the affected placement rows (`with_for_update`; SQLite ignores it), applies the change, bumps `knowledge_topics.version` and writes the records listed below, then commits once. Any failure, including a forced failure between the unplace and place halves of a move (covered by a test), rolls back everything and leaves the proposal approved.
- **Records written:**
  - for topic-level changes: a `knowledge_topic_versions` snapshot (the shared topic snapshot plus `placements`), a `knowledge_publication_records` row (`section_id` null) and a `knowledge_topic_audits` row (`map_<action>`, before = captured state, after = change and new snapshot);
  - for section changes and section restores: a section version and a publication record, as before;
  - in both cases, the existing review decision row.
- **Stale proposals:** a proposal is refused with 409 when:
  - `expected_version` does not match;
  - the section changed since `base_section_version`;
  - for map actions, the captured state no longer matches live data (for example, the placement was changed by another publish).

  Nothing is overwritten silently.
- **Batches:** the existing service has no batch publish, so map proposals publish one at a time. Each publish is atomic on its own.
- **History:** `GET /api/v1/knowledge/admin/topics/{id}/history` (admin) returns the shared topic history: audit rows, including every map change, and topic versions, from the same function as the legacy career-readiness endpoint. Section versions are added to it, all newest first, each with actor, reason and timestamp.

## Rollback

Rollback is a proposal (D6). `RESTORE_VERSION` goes through review and publish like any other change and never deletes history.

- **Section:** `{"target": "section", "section_type", "version"}` republishes that stored section version's content as a new section version (for example, restoring version 1 after version 2 creates version 3 with version 1's content). The usual `base_section_version` check applies.
- **Topic:** `{"target": "topic", "version"}` restores the stored snapshot's name, description, category, display order, aliases, parent (cycle-checked), active state, placements and career-level rows. Placements are put back exactly: missing ones are placed, and extra ones are unplaced while keeping their domain links. Snapshots recorded before KM-4 have no `placements` key; restoring one leaves placements unchanged. Restore is the one action allowed on an inactive topic, so restoring a version from when it was active brings it back.
- In Knowledge Map Management, "Restore version" lists topic and section versions from the history endpoint.

## Code

| File | Purpose |
|---|---|
| `backend/migrations/versions/phase_13_knowledge_map_placement.py` | Migration `ph13mapplacement` |
| `backend/app/knowledge_map_api.py` | Routes, ETag and caching |
| `backend/app/knowledge_map_service.py` | Hierarchy, counts, placements, search, ETag |
| `backend/app/knowledge_map_schemas.py` | Response models |
| `backend/tests/test_knowledge_map.py` | Tests, including migration upgrade and downgrade |
| `frontend/src/KnowledgeMapPage.jsx` | Map page: state, on-demand loading, search, deep links, toolbar, details panel |
| `frontend/src/KnowledgeMapGraph.jsx` | Graph view (`@xyflow/react`), lazy loaded |
| `frontend/src/KnowledgeMapTree.jsx` | Accessible tree view |
| `frontend/src/knowledgeMapModel.js` | Pure state, visible tree and layout helpers |
| `frontend/tests/KnowledgeMap.test.jsx` | Page, navigation and model tests |
| `backend/app/knowledge_content_schemas.py` | `code_examples`, `architecture` and diagram schemas; read-path filtering of invalid diagrams |
| `backend/tests/test_knowledge_content.py` | Section schema, legacy content and relationship tests |
| `frontend/src/KnowledgeMapTopicPanel.jsx` | Topic detail panel and career level selector |
| `frontend/src/KnowledgeSections.jsx` | Section renderers shared with the Knowledge Base topic page |
| `frontend/src/KnowledgeDiagram.jsx`, `KnowledgeDiagramCanvas.jsx`, `knowledgeDiagramLayout.js` | Diagram renderer, lazy canvas and pure layout |
| `frontend/src/KnowledgeCodeBlock.jsx` | Syntax highlighting (`prism-react-renderer`), lazy loaded |
| `frontend/tests/KnowledgeTopicDetail.test.jsx` | Topic panel, renderer, diagram layout and editor tests |
| `backend/app/knowledge_map_proposals.py` | Map action payloads, validation, captured state, apply, preview helpers, duplicate detection |
| `backend/tests/test_knowledge_map_proposals.py` | Map proposal lifecycle, atomicity, cycles, duplicates, restore, preview and end-to-end tests |
| `frontend/src/KnowledgeMapAdminPage.jsx` | Knowledge Map Management |
| `frontend/src/knowledgeMapActions.js` | Map action labels and the review line diff |
| `frontend/src/KnowledgeSectionForms.jsx` | Structured `code_examples` and `architecture` editors |
| `frontend/tests/KnowledgeMapAdmin.test.jsx` | Management payloads, Pending badges, Mind Map Changes review and publish |
