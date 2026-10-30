# Knowledge Map Step KM-5 — Initial Content and AI Proposals

Read `00-shared-context.md` first. Requires Step KM-4 merged.

## Goal

Validate the whole workflow with a few high-quality example topics, and let administrators turn an approved research
finding into map proposals using the existing AI configuration. Nothing in this step publishes automatically.

## 1. Assessment

- Map the existing published knowledge topics: list each with its domain links and propose (in the report, not in code)
  which branch each belongs to. Submit those as `PLACE_TOPIC` proposals only after the report is reviewed, or provide a
  script that creates them for an administrator to run.
- Read `ai_providers.py`, `model_selection.py`, `research_review_service.py` and how findings are produced.
- Record the baseline.

## 2. Initial example topics (as proposals)

Create a re-runnable, idempotent script (for example `backend/app/knowledge_map_examples.py`, invoked manually,
**not** from startup or `seed.py`) that submits proposals with `source_type = "manual"` and stable idempotency keys:

| Topic | Placement (adjust to the live taxonomy) |
|---|---|
| IDOR / BOLA | Cloud API Security → Common Vulnerabilities; Web Application Security → Common Vulnerabilities |
| OAuth 2.0 | Identity and Access Management → Security; Cloud API Security → Security |
| SSRF | Cloud API Security → Common Vulnerabilities; Web Application Security → Common Vulnerabilities |
| Secure Boot | the appropriate Embedded Systems Security child domain → Security |
| Firmware Signature Verification | the appropriate Embedded Systems Security child domain → Security |

For each: overview, how it works (with a vulnerable and a secure flow diagram where relevant), code examples where
meaningful, attack surface, mitigations, relationships (e.g. HTTP → REST API prerequisites, IDOR `mitigated_by`
object-level authorization), and career-level expectations for each active level that genuinely differ.

Real-world examples and references:
- Use only sources you can cite with a URL (vendor advisories, NVD, OWASP, standards, CISA KEV for exploitation).
- Mark everything `verification_status = "unverified"` for the administrator to verify.
- Do not state exploitation in the wild unless the cited source says so.
- If you cannot find a citable example, leave `real_world_examples` empty and note it in the proposal reason.
- Before creating a topic, reuse an existing one if it already exists (Step KM-4 duplicate check).

Acceptance: an administrator can review, modify, approve and publish these from the Mind Map Changes tab, and the
public map then shows them.

## 3. AI decomposition of research findings

Add an **admin-triggered** action; do not change ingestion or scheduling behaviour.

- `POST /api/v1/knowledge/admin/findings/{finding_id}/map-suggestions` (admin): takes an approved research finding
  (for example "Experience securing cloud-native APIs"), calls the configured model through the existing provider and
  model-selection code, and returns **suggestions** (not yet proposals).
- Before calling the model, gather candidate existing topics (name, aliases, topic_key) for the finding's domains and
  include them so the model prefers linking to existing topics.
- The model must return JSON matching a strict schema: `[{action: "PLACE_TOPIC"|"CREATE_TOPIC"|"ADD_TOPIC_RELATIONSHIP",
  existing_topic_id?, name?, domain_id, map_branch, rationale}]`. Invalid output → error shown to the admin, nothing stored.
  Validate every id against the database; drop unknown ids.
- In the UI (Research Review finding view, or Knowledge Map Management), the admin selects which suggestions to submit.
  Selected ones become proposals with `source_type = "ai"`, linked to the finding (`finding_id`) and its evidence.
- Job-description evidence may justify that employers expect the topic; it is never used as a source for technical
  content. AI-created topics carry name and placement only; technical sections are left for later proposals.
- Treat model output as untrusted text: same cleaning and URL validation as all proposals.

## 4. RAG readiness (documentation only)

Document in `docs/knowledge-map.md` how a future RAG service submits content: the contract proposal endpoint with
`source_type = "rag"`, an idempotency key, `KnowledgeSourceReference` provenance, and the section schemas from Step KM-3.
Do not build a RAG engine.

## 5. Tests

1. Example script is idempotent (second run creates nothing) and creates proposals only — no published rows change.
2. Example script reuses an existing topic instead of duplicating it.
3. Map-suggestions with a mocked provider: valid output returns suggestions; invalid JSON, unknown ids and extra keys
   are rejected or dropped; nothing is written to the database.
4. Submitting selected suggestions creates `source_type = "ai"` proposals linked to the finding.
5. Endpoint requires the admin key.
6. JSearch, Yahoo Mail, Research Ingestion and Research Review tests pass unchanged.

## 6. Final acceptance demonstration (whole feature)

Run and record (screenshots or step log):
1. Open Explore → Security Knowledge Map; domains match Taxonomy Management.
2. Expand Cloud API Security → Common Vulnerabilities → IDOR / BOLA.
3. Read the overview; view vulnerable vs secure code; view the attack flow; view mitigations and references.
4. Switch career level Junior → Senior; Knowledge and Practical Skills change.
5. Open Administration → Knowledge Map Management; propose a change to an existing topic.
6. Open Knowledge Review → Mind Map Changes; inspect before/after; modify; approve.
7. Confirm the public map is unchanged before publishing; publish; confirm the change appears.
8. Reject a different proposal; confirm it never appears.
9. Restore the earlier version through a proposal; confirm history shows all versions.
10. Smoke-test Dashboard, Domain Explorer, Career Matrix, Career Comparison, Competency Explorer, Career Readiness,
    Knowledge Base, Research Ingestion, Research Review, Yahoo Job Alerts, Taxonomy Management, AI Model Configuration.

Report anything you could not test as untested.
