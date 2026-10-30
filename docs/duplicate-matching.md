# Duplicate skills and knowledge topics

Research ingestion (`process_submission`, used by URL imports, the research scheduler and Yahoo job alerts) links new findings to skills (competencies) and knowledge topics that already exist, instead of proposing near-identical new ones.

## How names are compared

`backend/app/name_matching.py` reduces a name to its significant word stems, then scores the overlap.

- **Normalising:** it lowercases, removes punctuation and expands abbreviations (DFIR, IR, IAM, K8s, …). It drops filler words that describe the job ad rather than the skill ("experience", "skills", "knowledge", "security", "cyber", …), and stems plurals and word endings ("leadership" and "leading" both become "lead").
- **Scoring:** 1.0 means the same significant words. Word overlap and character similarity cover rewordings.
- **Thresholds:**
  - **0.85 and above** counts as the same item and is linked automatically. Examples: "Incident response" = "Security incident response"; "Leading security engineering programs" = "Security engineering program leadership".
  - **0.60 to 0.85** is shown to the reviewer as a possible duplicate and is never linked automatically. For example, "Security team leadership and mentoring" scores 0.82 against "Cybersecurity deal-team leadership and mentoring", but is a different skill.

## Skills (Research Review)

1. **Extraction prompt:** the model is told to copy the exact name of a skill from `competencies` (published) or `proposed_competencies` (up to 150 new skills awaiting review) when the requirement is the same skill. Otherwise it uses a short, general skill name.
2. **Ingestion:** after exact and alias matching, the matcher links a finding to a published skill when the score is 0.85 or above. The review change then becomes a new or updated expectation for that skill, so its details are updated rather than a new skill being created. Failing that, the finding takes the name of an equivalent skill already awaiting review, so all of them share one name.
3. **Review:** each change shows a "Duplicate check":
   - the automatic match, if there was one;
   - "Same new skill as review change #N";
   - close published skills (0.60–0.85). To merge into one of those, edit the competency name to that skill's name.
4. **Publish:** a new skill whose name matches an existing skill exactly or at 0.85 or above is published into that skill. No second skill is created.

## Knowledge topics (Career Readiness Review)

1. **Matching:** a finding matches a published topic by exact name or alias. If none matches, it uses the topic linked to the finding's skill. Otherwise it uses a similar name (0.85 or above).
2. **One open update per topic:** later findings for the same topic join that topic's open proposal. They add domains, industries, missing career levels and evidence, with an audit entry, instead of creating another proposal.
3. **New topics:** a finding whose new topic matches one already awaiting review joins that proposal, and its wording is kept as an alias.
4. **Publish:** a new topic that matches an existing topic by slug or similar name is merged into it, with its name added as an alias. No duplicate topic is created.

## Cleaning up the existing backlog

```bash
docker compose exec backend python -m app.duplicate_consolidation           # dry run: report only
docker compose exec backend python -m app.duplicate_consolidation --apply   # apply
```

It only touches items still awaiting review. Approved, published and rejected items are left alone.

- **Skills:** pending new skills matching a published skill become updates to it. Pending new skills that mean the same thing take one shared name.
- **Topics:** pending new topics and duplicate open updates are folded into one proposal per topic. Folded proposals get status `merged`, and their evidence moves to the proposal that absorbed them.
- Every change is audited, and re-running changes nothing.

On a copy of the live data (2026-10-30) the dry run reported:

- 5,073 duplicate open topic updates folded into one per topic, leaving 36 open topic updates instead of 5,109;
- 151 duplicate new-topic proposals folded, including 58 repeats of an already-published topic;
- 23 pending new skills renamed to match an equivalent pending skill.
