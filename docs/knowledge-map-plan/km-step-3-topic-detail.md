# Knowledge Map Step KM-3 — Topic Detail Panel, Code Examples, Diagrams, Career Levels

Read `00-shared-context.md` first. Requires Step KM-2 merged.

## Goal

Selecting a topic shows its published learning content in tabs, including safe code examples, rendered diagrams,
and career-level expectations, all read from existing knowledge records.

## 1. Assessment

- Read `KnowledgeTopicPage.jsx`, `KnowledgeSectionEditor.jsx`, `knowledge_contract_schemas.py` and
  `knowledge_contract_service.py` (`_section_response`, public topic response, `ADD_DIAGRAM` handling).
- Note: `KnowledgeSectionEditor.jsx` hardcodes six career levels in `career_level_guidance`; report it (fixed in §5).
- Record the baseline.

## 2. Backend: two new section types (additive)

Add to `SECTION_TYPES` and the `SectionType` literal, with Pydantic content schemas validated on proposal create and review:

**`code_examples`**
```json
{ "items": [ {
  "title": "Order lookup",
  "language": "python",
  "vulnerable": "…",
  "secure": "…",
  "explanation": "…",
  "security_control": "Object-level authorization"
} ] }
```
- `language` from an allowlist (e.g. python, javascript, typescript, java, go, csharp, c, cpp, rust, php, ruby, http, json, yaml, bash).
- Each code field max 8,000 chars, max 6 items.

**`architecture`**
```json
{ "diagrams": [ {
  "kind": "architecture | sequence | trust_boundary | attack_path | flow",
  "title": "…",
  "variant": "vulnerable | secure | neutral",
  "nodes": [ { "id": "api", "label": "API", "type": "actor|service|datastore|control|external", "boundary": "internet" } ],
  "edges": [ { "from": "user", "to": "api", "label": "GET /orders/1002", "order": 1 } ],
  "boundaries": [ { "id": "internet", "label": "Internet" } ]
} ] }
```
- Strict schema: unknown keys rejected; ids match `^[a-z0-9_-]{1,40}$`; labels plain text ≤ 120 chars;
  max 40 nodes and 80 edges per diagram; edges must reference existing nodes; no style or URL fields.
- Reuse the same diagram schema to validate the existing `how_it_works.diagram` when present (read path tolerates
  legacy invalid diagrams by hiding them, never by crashing).

Existing sections and their content are unchanged. Proposals for the new types use the existing
`ADD_SECTION` / `UPDATE_SECTION` / `ADD_DIAGRAM` actions.

Ensure `GET /api/v1/knowledge/topics/{topic_identifier}` returns `level_expectations` (added in Step KM-1 if missing)
and relationships including the new types from §4.

## 3. Frontend: detail panel

Replace the Step KM-2 placeholder with `KnowledgeMapTopicPanel.jsx`. Reuse the rendering from `KnowledgeTopicPage.jsx`
by extracting shared section renderers into a component both pages use, instead of copying them.

Tabs (show only tabs that have published content; foundational topics naturally hide vulnerability tabs):

| Tab | Source |
|---|---|
| Overview | `overview` (short description first; technical explanation behind "Show technical details") |
| How It Works | `how_it_works` steps + its diagram; vulnerable/secure toggle when both diagram variants exist in `architecture` |
| Example Code | `code_examples` — side-by-side vulnerable / secure on desktop, stacked on mobile, explanation and control below |
| Attack Surface | `attack_surfaces` |
| Mitigations | `mitigations` |
| Real-World CVEs | `real_world_examples` |
| Architecture | `architecture` diagrams |
| Career Levels | `KnowledgeTopicLevel` (D5) |
| Related Topics | relationships with inverse labels (D4); clicking navigates the map to that topic |
| References | `references` with provenance fields and verification status |

Panel header: name, breadcrumb, all placements, "Open full topic page" link to the existing Knowledge Base topic view.

### Code display
- `prism-react-renderer` (pinned), rendering tokens as React elements. Code is never evaluated, never inserted as HTML.
- Clearly label "Vulnerable" and "Secure" with text and icon, not colour alone. Copy button per block.

### Diagram renderer (`KnowledgeDiagram.jsx`)
- Renders validated diagram JSON with `@xyflow/react` (read-only, no editing) and `d3-hierarchy`/simple layered layout;
  sequence diagrams as ordered lanes; trust boundaries as labelled grouped regions.
- Provide a text alternative listing steps in edge order (screen readers and reduced-motion users).
- Replace the raw-JSON diagram dump in `KnowledgeTopicPage.jsx` with this component.

### Real-World CVEs
- Show per item: identifier (if any), affected product, description, weakness (CWE), impact, reference link,
  verification status, and exploitation status.
- Exploitation status is displayed as "Exploited in the wild" **only** when the item's status says so and it is
  `verified`; otherwise "Publicly disclosed" or "Proof of concept". Unverified items carry an "Unverified" badge.
- No items → "No verified real-world example has been added."

### Career levels
- Level selector built from active `career_levels`, grouped by track (Shared, Technical, Management).
- For the chosen level show **Knowledge** (`expectation`) and **Practical Skills** (`practical_capability`) separately.
- Level with no row → "No expectations defined for this level yet." Do not copy another level's text.
- If the topic has no `KnowledgeTopicLevel` rows but has a legacy `career_level_guidance` section, show it read-only.

### Links
- Only http(s) links, `rel="noopener noreferrer"`, `target="_blank"`, URL shown on hover/focus.

## 4. Relationship types (backend)

- Extend the validator in `knowledge_schemas.py` and any contract-side validation to allow `mitigated_by` and `tested_by`.
- Response includes both outgoing and incoming relationships with a display label
  (incoming `dependency` → "Used by", incoming `mitigated_by` → "Protects against", incoming `tested_by` → "Tests").
- Reject self-relationships.

## 5. Fix hardcoded levels in the section editor

`KnowledgeSectionEditor.jsx` `career_level_guidance` defaults: build the level keys from the career levels API so
Guide and Supervisor are included. Existing saved content keeps working.

## 6. Tests

Backend:
1. New section schemas accept valid content and reject unknown keys, oversized fields, bad languages, dangling edges,
   `<script>`, and non-http URLs.
2. Legacy content without new sections still returns normally.
3. Relationship validation accepts new types, rejects self-links; incoming labels are correct.

Frontend:
4. Only tabs with content are shown.
5. Code renders as text: a payload such as `<img src=x onerror=alert(1)>` appears literally and creates no element.
6. Diagram renders nodes/edges and the text alternative; invalid diagram is hidden with a notice.
7. Career level switch (Junior → Senior) changes Knowledge and Practical Skills; missing level shows empty state.
8. CVE exploitation label rules and empty state.
9. Related topic click navigates the map.
10. Knowledge Base topic page still renders (shared renderers) and existing `KnowledgeTopic.test.jsx` passes.

## 7. Docs

Add "Content model" to `docs/knowledge-map.md`: both new section schemas, diagram schema, relationship types and
inverse labels, career-level source.

## Out of scope

Editing UI for the new sections beyond what the existing section editor gains automatically from `SECTION_TYPES`
(full editor support comes in Step KM-4).
