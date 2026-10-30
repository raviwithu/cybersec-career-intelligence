# Knowledge Map Step KM-4 — Knowledge Map Management, Review, Publication, Rollback

Read `00-shared-context.md` first. Requires Step KM-3 merged.
This step changes the publication workflow. Keep every existing proposal action behaving exactly as before.

## Goal

Administrators propose map changes, review them in the existing Knowledge Review page, and publish them
explicitly and transactionally. Earlier versions can be restored through the same workflow.

## 1. Assessment

- Read `knowledge_contract_service.py` end to end: create, review (`expected_version`), publish, merge, idempotency,
  fingerprints, provenance, audit and publication records.
- Read `KnowledgeReviewPage.jsx` and `KnowledgeSectionEditor.jsx`.
- Check what `UPDATE_CAREER_LEVEL_GUIDANCE` writes today (section vs `KnowledgeTopicLevel`).
- Record the baseline, including every existing knowledge-contract test.

## 2. New proposal actions (contract API)

Extend `ProposalAction` and the service. All go through `POST /api/v1/knowledge/proposals`, review and publish endpoints
that already exist. No new proposal tables or endpoints prefixes.

| Action | `proposed_content` | Publish effect |
|---|---|---|
| `PLACE_TOPIC` | `{domain_id, map_branch, display_order?}` | Upsert link, set branch |
| `UNPLACE_TOPIC` | `{domain_id}` | Set `map_branch = NULL` (keep link) |
| `MOVE_TOPIC` | `{from: {domain_id}, to: {domain_id, map_branch}}` | Unplace + place in one transaction |
| `REORDER_TOPICS` | `{domain_id, map_branch, ordered_topic_ids}` | Rewrite `display_order` for that branch |
| `SET_PARENT_TOPIC` | `{parent_topic_id or null}` | Update `parent_topic_id`; reject cycles at create **and** publish |
| `REMOVE_TOPIC_RELATIONSHIP` | `{target_topic_id, relationship_type}` | Delete that relationship row |
| `DEACTIVATE_TOPIC` | `{reason}` | `is_active = false`; topic disappears from the map |
| `UPDATE_CAREER_LEVELS` | `{levels: [{career_level_id, industry_id?, expectation, practical_capability}]}` | Upsert `KnowledgeTopicLevel` rows listed; others untouched |
| `RESTORE_VERSION` | `{target: "topic" or "section", section_type?, version}` | Republish the stored snapshot as a new version |

Rules:
- Validation at create **and** re-validation at publish (state may have changed): domain active, topic exists and is
  active (except for restore), branch valid, no cycle, reorder list matches the current branch members exactly.
- `CREATE_TOPIC` gains an optional `placements` list so a new topic and its placement publish together.
- Before `CREATE_TOPIC`, search existing topics by normalized name, slug, `topic_key` and aliases. If a match exists,
  reject with 409 and the matching topic id, suggesting `PLACE_TOPIC` or a section update instead.
- `original_content` captures the current state for before/after comparison.
- Keep `UPDATE_CAREER_LEVEL_GUIDANCE` working as it does today for backward compatibility.
- Change reason is required for every map action.

### Publication
- Publish holds row locks (`with_for_update`, as existing code does) on the affected topic and placement rows,
  applies the change, bumps versions, writes `KnowledgeTopicVersion` / section version, `KnowledgePublicationRecord`
  and audit rows, and commits once. Any failure rolls back everything.
- Publishing a stale proposal (`expected_version` mismatch, or the topic/section changed since `base_*_version`) → 409.
  Never silently overwrite.
- Batch publish (if the existing service supports batches) publishes related proposals in one transaction.
- Approved ≠ published: approval never changes live tables.

### Preview
- `GET /api/v1/knowledge/admin/proposals/{id}/map-preview` (admin): affected branches `{before, after}` computed from
  live data plus this proposal, without writing.

### Version history
- `GET /api/v1/knowledge/admin/topics/{id}/history` may already exist in one of the two systems; reuse it.
  It must list topic and section versions with actor, reason and timestamps, and placement changes from the audit.

## 3. Admin UI

### Knowledge Map Management (Administration group, new item)
`KnowledgeMapAdminPage.jsx`, admin key required (existing pattern):
- Browse the map using the Step KM-2 components with an admin flag that also shows topics with **pending** proposals
  (amber "Pending" badge with text) — read from proposals, not from live data.
- Actions open forms that create proposals: add/edit topic (reuse `KnowledgeSectionEditor`, now with
  `code_examples` and `architecture` editors), place, move, reorder (up/down buttons; drag optional), set parent,
  add/remove relationship, merge duplicates (existing merge action), deactivate, edit career levels per level, restore version.
- Warn when placing on a domain that has child domains (D1).
- Link to Taxonomy Management for domain CRUD; no domain editing here.
- Topic search with a "possible duplicates" hint before creating.

### Knowledge Review — "Mind Map Changes" tab
Extend `KnowledgeReviewPage.jsx` with a tab filtered to the new actions (plus `CREATE_TOPIC` with placements).
Each proposal shows: action, source type, status, submitter, change reason, evidence (existing evidence view),
before/after (text diff for content, branch tree for hierarchy using map-preview), and the existing
Approve / Modify / Merge / Reject / Defer controls, then a separate Publish step for approved proposals.

## 4. Tests

Backend (`test_knowledge_map_proposals.py`):
1. Each new action: create → approve → publish updates live data; before publish the public map is unchanged.
2. Reject and defer leave live data unchanged.
3. Modify changes `proposed_content` and bumps the proposal version; stale review/publish → 409.
4. `MOVE_TOPIC` is atomic: a forced failure mid-publish leaves the original placement intact.
5. Cycle prevention for `SET_PARENT_TOPIC` at create and at publish (cycle introduced by another publish in between).
6. `CREATE_TOPIC` duplicate detection by name, slug and alias → 409 with the existing id.
7. Cross-domain placement keeps one topic row.
8. `RESTORE_VERSION` publishes old content as a new version; history keeps all versions.
9. Publish without admin key → 401/403; public endpoints still show only published data.
10. All existing knowledge-contract and career-readiness tests pass unchanged.

Frontend:
11. Management actions submit the correct proposal payloads.
12. Pending badge appears only in admin view, never on the public map.
13. Mind Map Changes tab lists proposals, shows before/after, and runs review then publish.
14. Existing Knowledge Review tabs still work.

Integration: a scripted end-to-end test (backend test client) of propose → modify → approve → publish → public map
shows change; and propose → reject → public map unchanged.

## 5. Docs

Add "Admin and review workflow", "Publication and versioning" and "Rollback" sections to `docs/knowledge-map.md`,
including every action's payload.

## Out of scope

AI-generated proposals and initial content (Step KM-5).
