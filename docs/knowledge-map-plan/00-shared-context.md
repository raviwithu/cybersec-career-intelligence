# Security Knowledge Map — Shared Context (read before every step)

Project: CyberSec Career Intelligence
Workspace: `/projects/cybersec-career-intelligence`

This is an **enhancement to an existing application**. Inspect before changing anything. If anything below
no longer matches the code, trust the code, and report the difference in your completion report.

---

## 1. Purpose

An interactive, expandable map that turns cybersecurity domains into learnable topics:

```text
CyberSec Career Intelligence            (root)
└── Security Domain                     (security_domains, top level)
    ├── Child Domain                    (security_domains with parent_id, when the taxonomy has them)
    │   └── Branch → Topic
    └── Branch                          (Foundations | Security | Common Vulnerabilities)
        └── Topic                       (knowledge_topics, published only)
            └── Detail panel            (sections, code, diagrams, career levels, references)
```

Branches always belong to a specific domain. They are never shared top-level categories.

---

## 2. Repository facts (verified)

### Stack
- Backend: FastAPI + SQLAlchemy + Alembic, in `backend/app/`. API prefix `/api/v1` (`config.py`).
- Frontend: React 19 + Vite, plain JSX in `frontend/src/`, Vitest tests in `frontend/tests/`.
  No graph, Markdown or syntax-highlighting library is installed.
- Tests: backend `cd backend && pytest` (SQLite fixture in `tests/conftest.py`);
  frontend `cd frontend && npm test && npm run build`.
- Last recorded baseline (`AGENTS.md`): Alembic head `ph12dunblockresolved`, 167 backend and 63 frontend tests passing.
  Re-run and record the real baseline at the start of every step.
- Admin authorization is a single admin key enforced by `require_admin` (`admin_auth.py`).
  "Reviewer" means the actor string already recorded by the existing review code. Do not build roles.

### Taxonomy (`models.py`, `seed.py`)
- `SecurityDomain` supports nesting through `parent_id`. Seeded top-level domains include Web Application Security,
  Cloud API Security, Cloud Infrastructure Security, Traditional Server Infrastructure Security, Embedded Systems Security,
  Governance Risk and Compliance, Identity and Access Management, Security Operations, AI System Security.
- **Only Embedded Systems Security has child domains** (`EMBEDDED_SUBDOMAINS`). There is no "Application Security" parent
  and no "API Security" subdomain. Read the live database, not the seed list.
- `CareerLevel` has `career_track` (`shared | technical | management`). Currently 8 levels:
  Junior, Intermediate, Senior (shared); Architect (technical); Guide, Supervisor, Manager, Director (management).
- Domain and level CRUD belongs to the existing **Taxonomy Management** page and `taxonomy_api.py`. Do not duplicate it.

### Knowledge model
- `KnowledgeTopic`: `name`, `slug`, `topic_key`, `description`, `parent_topic_id`, `aliases`, `publication_status`,
  `is_active`, `version`, `published_at`.
- `KnowledgeTopicDomain`: topic ↔ domain link, primary key `(topic_id, domain_id)`. Used by Career Readiness.
- `KnowledgeTopicLevel`: per topic, per career level (optionally per industry): `expectation` (knowledge) and
  `practical_capability` (practical skills).
- `KnowledgeTopicSection` + `KnowledgeTopicSectionVersion`: versioned JSON content per `section_type`.
  `SECTION_TYPES` (`knowledge_contract_schemas.py`): overview, how_it_works, attack_surfaces, mitigations,
  real_world_examples, references, career_level_guidance.
  `how_it_works` already holds a `diagram: {nodes, edges}` that `KnowledgeTopicPage.jsx` prints as raw JSON.
- `KnowledgeTopicRelationship`: `(source, target, relationship_type)`; validator in `knowledge_schemas.py` allows
  `prerequisite | related | specialization | dependency`.
- `KnowledgeTopicVersion`: topic snapshots.

### Proposal and review systems (two exist)
1. **Knowledge contract** — `knowledge_contract_api.py` (prefix `/knowledge`) and `knowledge_contract_service.py`.
   Has `source_type` (`manual | jsearch | ai | rag | connector`), review actions (approve, modify, merge, reject, defer),
   `expected_version` concurrency checks, idempotency keys, provenance in `KnowledgeProposalSource`,
   `KnowledgeReviewDecision`, `KnowledgePublicationRecord`. UI: `KnowledgeReviewPage.jsx`, `KnowledgeSectionEditor.jsx`.
2. **Legacy career-readiness proposals** — `knowledge_topic_api.py` (prefix `/research/career-readiness`).

**The knowledge contract is the canonical system for all map changes.** Leave the legacy system working and unchanged.

### Navigation
`SidebarNavigation.jsx` groups: Explore, Career Development, Research Intelligence, Administration.
There is no "LEARN" group. The public map goes under **Explore**, next to Knowledge Base.

---

## 3. Design decisions (apply in every step)

**D1. Hierarchy follows existing taxonomy nesting.**
The map shows active top-level domains under the root. Expanding a domain shows its active child domains (if any),
then its branch nodes (only branches that contain at least one published placement).
Placements are allowed on any active domain; Knowledge Map Management warns when placing on a domain that has children.
Do not create, rename or restructure domains in this feature. Restructuring is done in Taxonomy Management.

**D2. Branch placement extends `knowledge_topic_domains`.**
One additive migration adds nullable `map_branch` (`foundations | security | vulnerabilities`) and `display_order`
(default 0). Existing rows get `map_branch = NULL` and do not appear on the map.
- A topic has at most one branch per domain, and may be placed in many domains (cross-domain mapping, one canonical topic).
- Placing a topic in a domain it is not yet linked to creates the link. This intentionally also makes the topic appear
  for that domain in Career Readiness; document this.
- Removing a placement sets `map_branch = NULL`. It never deletes the domain link.
- The public map reads only placements whose topic is `publication_status = 'published'` and `is_active`.

**D3. Unpublished changes live in proposals.**
Map changes are stored in `knowledge_topic_proposals.proposed_content` and written to live tables only by the publish step,
in a single transaction. Live tables therefore always represent the published map; no shadow tables.

**D4. Relationship types.**
Stored types: `prerequisite`, `related`, `specialization`, `dependency`, `mitigated_by`, `tested_by`.
Displayed inverses (never stored): `dependency` ⇄ "used by", `mitigated_by` ⇄ "protects against", `tested_by` ⇄ "tests".
Parent/child stays `parent_topic_id`. Reject self-relationships and parent cycles.

**D5. Career levels.**
The canonical source is `KnowledgeTopicLevel` (expectation = Knowledge, practical_capability = Practical Skills).
The `career_level_guidance` section is legacy: show it read-only only when a topic has no `KnowledgeTopicLevel` rows.
Level lists always come from the active `career_levels` rows grouped by `career_track`, never hardcoded.

**D6. Rollback is a proposal.**
Restoring an earlier version creates a proposal (Step KM-4) that goes through review and publish like any other change.

**D7. Frontend libraries.**
Graph: `@xyflow/react` with `d3-hierarchy` for layout. Code: `prism-react-renderer`.
Pin exact versions confirmed compatible with React 19. Add no other UI framework.
No Markdown rendering in this feature: render all content as React text nodes. Never use `dangerouslySetInnerHTML`.

**D8. Diagrams are data.**
Diagrams are validated JSON (nodes, edges, optional lanes/boundaries) rendered by our own component.
No Mermaid, no SVG/HTML strings, no scripts, no arbitrary styling from content.

---

## 4. Non-negotiable rules

- Additive Alembic migrations only. Chain from the current head. Provide a working downgrade.
- Do not delete or rename tables, columns, endpoints or taxonomy identifiers.
- Do not change existing ingestion behaviour (JSearch, Yahoo Mail, research automation, scheduler).
- Do not publish anything automatically. AI, RAG and seed content enter as proposals.
- Do not fabricate topics, CVEs, or exploitation claims. Missing data shows an explicit empty state.
- Do not modify Docker Compose services. Ollama stays external at `host.docker.internal:11434`.
- Public endpoints return published data only. Admin endpoints use `require_admin`.
- Treat proposal content, retrieved documents and AI output as untrusted: validate with Pydantic schemas,
  reuse `_clean_value` / `validate_proposed_content_urls`, allow only http(s) URLs.
- Job descriptions may support employer-expectation claims only, never vulnerability mechanics, code or CVE details.
- Do not change unrelated code to make tests pass.

---

## 5. Every step must

1. Record the baseline: backend and frontend test counts and failures, frontend build result, Alembic head.
2. Implement only the step scope. List anything deferred.
3. Add tests for new behaviour.
4. Re-run all tests and the build. Separate pre-existing failures from new ones.
5. Update `docs/knowledge-map.md` (create it in Step KM-1) and the repository memory in `AGENTS.md`.
6. Produce a completion report: summary, files changed, migrations, endpoints, tests before/after,
   known limitations, how to run. Do not report untested behaviour as working.
