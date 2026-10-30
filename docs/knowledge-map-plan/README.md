# Security Knowledge Map — Implementation Plan

This folder replaces the original single "Interactive Cybersecurity Knowledge Mind Map" specification.
The original asked for everything at once and assumed a data model the repository does not have.
This version is grounded in the actual code and split into five steps (KM-1 to KM-5) that each ship independently.

## How to use these files

For each step, give the implementing agent **two files**:

1. `00-shared-context.md` — repository facts, design decisions, and non-negotiable rules (same for every step)
2. The step file (`km-step-N-*.md`)

Run the steps in order. Do not start a step until the previous step is merged and its tests pass.
Each step ends with a completion report; review it before starting the next step.

| Step | File | Delivers | Depends on |
|---|---|---|---|
| KM-1 | `km-step-1-backend-hierarchy.md` | Placement migration, published hierarchy APIs, search | — |
| KM-2 | `km-step-2-map-interface.md` | Map page, tree view, navigation, search UI | KM-1 |
| KM-3 | `km-step-3-topic-detail.md` | Detail panel, code examples, diagram renderer, career levels | KM-2 |
| KM-4 | `km-step-4-admin-and-review.md` | Map management, proposal actions, review tab, publish, rollback | KM-3 |
| KM-5 | `km-step-5-content-and-ai.md` | Initial example topics (as proposals), AI decomposition proposals | KM-4 |

Steps KM-1 to KM-3 are read-only for public users and change no existing write path.
Step KM-4 is the riskiest (it touches the publication workflow); review it most carefully.

## What changed from the original specification

| Original | Revised | Why |
|---|---|---|
| Domain → Subdomain hierarchy such as "Application Security → API Security" | Map follows the existing `security_domains` nesting. Only Embedded Systems Security has subdomains today; other domains are top-level and hold the branches directly | Inventing parent domains would duplicate taxonomy and affect job classification |
| Foundations / Security / Common Vulnerabilities as new entities | Nullable `map_branch` column on the existing `knowledge_topic_domains` link | Reuses the existing topic↔domain mapping; one canonical topic, many placements |
| New `/admin/knowledge-map/proposals` endpoints | New actions on the existing knowledge contract API (`/knowledge/proposals`) | Two proposal systems already exist; a third would fragment review |
| Separate "Knowledge Map Review" page | "Mind Map Changes" tab in the existing Knowledge Review page | Reuse existing review infrastructure |
| 6 career levels (Junior … Director) | All active career levels from taxonomy (currently 8, three tracks) | Guide and Supervisor exist in the management track |
| Knowledge vs Practical Skills as new structures | `KnowledgeTopicLevel.expectation` and `.practical_capability` | Already modelled per level |
| Relationship types incl. Parent/Child, Used By, Protects Against | Parent/child stays `parent_topic_id`; inverse pairs stored once and displayed both ways | Avoids contradictory duplicate edges |
| Rollback as a direct revert | Rollback is a proposal that restores an earlier version | Keeps every published change reviewed |
| Page under "LEARN" | Page under the existing **Explore** sidebar group | There is no LEARN group |
| "Evaluate graph libraries" | `@xyflow/react` + `d3-hierarchy`, `prism-react-renderer` named explicitly | Removes an open-ended choice |
| Initial example topics created directly | Example topics enter as proposals in review, references unverified | Consistent with "never auto-publish" |
| Four documentation files | One `docs/knowledge-map.md`, extended each step | Matches existing `docs/` style |
