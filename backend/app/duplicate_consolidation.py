"""Consolidate duplicate skills and knowledge topics already waiting in the review queues. Run manually.

    python -m app.duplicate_consolidation            # dry run: report what would change, write nothing
    python -m app.duplicate_consolidation --apply    # apply the changes

Only items still awaiting review are touched; approved, published and rejected items are left alone, and every
change is recorded in the item's audit trail.

Skills (Research Review): a pending "new skill" whose name means the same as a published skill becomes an update to
that skill; pending new skills that mean the same thing take one shared name, so publishing creates one skill.
Topics (Career Readiness Review): a pending "new topic" that matches a published topic, or another pending new
topic, is folded into one proposal; several open updates for the same topic are folded into the oldest one.
Folded proposals get status "merged" and their evidence moves to the proposal that absorbed them.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from .database import SessionLocal
from .duplicate_matching import competency_names
from .knowledge_topic_service import _matching_topic, _with_additions, now, snapshot, topic_query
from .models import Competency, KnowledgeTopic, KnowledgeTopicAudit, KnowledgeTopicEvidence, KnowledgeTopicProposal, ResearchFinding, ReviewAudit, ReviewChange
from .name_matching import STRONG_MATCH, best_match
from .research_review_service import _find_expectations

OPEN_SKILL_STATUSES = ("pending", "modified")


class Report:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.examples: dict[str, list[str]] = {}

    def add(self, kind: str, example: str) -> None:
        self.counts[kind] += 1
        bucket = self.examples.setdefault(kind, [])
        if len(bucket) < 8:
            bucket.append(example)

    def lines(self) -> list[str]:
        out = []
        for kind, count in self.counts.most_common():
            out.append(f"{count:6d}  {kind}")
            out.extend(f"          e.g. {example}" for example in self.examples.get(kind, []))
        return out or ["No duplicates found."]


def _audit_change(change: ReviewChange, action: str, before: dict, note: str) -> None:
    change.version += 1
    change.updated_at = now()
    change.audits.append(ReviewAudit(action=action, actor="system", before_snapshot=before, after_snapshot=deepcopy(change.proposed_snapshot), note=note))


def consolidate_skills(db: Session, report: Report) -> None:
    competencies = list(db.scalars(select(Competency)).all())
    changes = list(db.scalars(select(ReviewChange).where(ReviewChange.change_type == "new_competency", ReviewChange.status.in_(OPEN_SKILL_STATUSES)).options(selectinload(ReviewChange.finding), selectinload(ReviewChange.audits)).order_by(ReviewChange.id)).all())
    canonical: list[str] = []
    first_change: dict[str, int] = {}
    for change in changes:
        name = (change.proposed_snapshot.get("competency_name") or "").strip()
        if not name:
            continue
        match, score = best_match(name, competencies, competency_names)
        before = deepcopy(change.proposed_snapshot)
        if match is not None and score >= STRONG_MATCH:
            finding = change.finding
            finding.competency_id = match.id
            finding.normalized_name = match.name
            expectations = _find_expectations(db, finding)
            change.change_type = "update_expectation" if expectations else "new_expectation"
            change.target_competency_id = match.id
            change.target_expectation_id = expectations[0].id if expectations else None
            change.proposed_snapshot = {**before, "competency_name": match.name, "skill_match": {"method": "similar_published_skill", "matched": match.name, "score": score}}
            _audit_change(change, "auto_matched", before, f"“{name}” matches the published skill {match.name} (similarity {score:.2f}); proposing an update instead of a new skill.")
            report.add("skill: new skill -> update of a published skill", f"{name} -> {match.name} ({score:.2f})")
            continue
        twin, twin_score = best_match(name, canonical, lambda value: [value])
        if twin is not None and twin_score >= STRONG_MATCH:
            if twin != name:
                change.proposed_snapshot = {**before, "competency_name": twin, "same_new_skill_as_change_id": first_change[twin.casefold()], "skill_match": {"method": "similar_pending_skill", "matched": twin, "score": twin_score}}
                change.finding.normalized_name = twin
                _audit_change(change, "auto_matched", before, f"“{name}” means the same as the pending new skill “{twin}”; using one name so publishing creates a single skill.")
                report.add("skill: renamed to match another pending new skill", f"{name} -> {twin} ({twin_score:.2f})")
            else:
                report.add("skill: same name as another pending new skill (already shared)", name)
            continue
        canonical.append(name)
        first_change[name.casefold()] = change.id


def _absorb(db: Session, keeper: KnowledgeTopicProposal, other: KnowledgeTopicProposal, alias: str | None = None) -> None:
    data = other.proposed_snapshot or {}
    before = deepcopy(keeper.proposed_snapshot)
    merged = _with_additions(keeper.proposed_snapshot, data.get("domain_ids", []), data.get("industry_ids", []), data.get("level_expectations", []), alias=alias)
    merged["related_competency_ids"] = sorted(set(merged.get("related_competency_ids", []) + data.get("related_competency_ids", [])))
    if merged != before:
        keeper.proposed_snapshot = merged
        keeper.version += 1
        if keeper.proposal_type == "evidence_update":
            keeper.proposal_type = "topic_update"
    keeper.updated_at = now()
    db.execute(update(KnowledgeTopicEvidence).where(KnowledgeTopicEvidence.proposal_id == other.id).values(proposal_id=keeper.id, topic_id=keeper.topic_id))
    other.status = "merged"
    other.version += 1
    other.review_note = f"Merged into proposal {keeper.id} as a duplicate."
    other.updated_at = now()
    db.add(KnowledgeTopicAudit(topic_id=keeper.topic_id, proposal_id=keeper.id, action="proposal_consolidated", actor="system", before_snapshot=before, after_snapshot=keeper.proposed_snapshot, reason=f"Duplicate proposal {other.id} merged into this proposal."))
    db.add(KnowledgeTopicAudit(topic_id=other.topic_id, proposal_id=other.id, action="proposal_merged", actor="system", before_snapshot=data, after_snapshot=None, reason=f"Merged into proposal {keeper.id} as a duplicate."))


def consolidate_topics(db: Session, report: Report) -> None:
    topics = list(db.scalars(topic_query().where(KnowledgeTopic.publication_status == "published", KnowledgeTopic.is_active.is_(True))).unique().all())
    open_query = select(KnowledgeTopicProposal).where(KnowledgeTopicProposal.contract == "legacy", KnowledgeTopicProposal.status == "review").options(selectinload(KnowledgeTopicProposal.finding)).order_by(KnowledgeTopicProposal.id)
    proposals = list(db.scalars(open_query).all())
    keepers: dict[int, KnowledgeTopicProposal] = {}
    # Open updates: one per topic.
    for proposal in proposals:
        if proposal.proposal_type not in ("topic_update", "evidence_update") or proposal.topic_id is None:
            continue
        keeper = keepers.setdefault(proposal.topic_id, proposal)
        if keeper is not proposal:
            _absorb(db, keeper, proposal)
            report.add("topic: duplicate open update merged into the topic's oldest open update", f"proposal {proposal.id} -> {keeper.id} ({keeper.topic.name if keeper.topic else keeper.topic_id})")
    # New topics: fold into a published topic, or into an earlier new topic with the same meaning.
    new_keepers: list[KnowledgeTopicProposal] = []
    for proposal in proposals:
        if proposal.proposal_type != "new_topic" or proposal.topic_id is not None:
            continue
        name = (proposal.proposed_snapshot or {}).get("name", "")
        finding = proposal.finding or ResearchFinding(competency_id=None)
        topic = _matching_topic(topics, finding, name)
        if topic is not None:
            keeper = keepers.get(topic.id)
            if keeper is None:
                before = deepcopy(proposal.proposed_snapshot)
                data = before or {}
                proposal.topic_id = topic.id
                proposal.proposal_type = "topic_update"
                proposal.original_snapshot = snapshot(topic)
                proposal.proposed_snapshot = _with_additions(snapshot(topic), data.get("domain_ids", []), data.get("industry_ids", []), data.get("level_expectations", []), alias=name)
                proposal.version += 1
                db.execute(update(KnowledgeTopicEvidence).where(KnowledgeTopicEvidence.proposal_id == proposal.id).values(topic_id=topic.id))
                db.add(KnowledgeTopicAudit(topic_id=topic.id, proposal_id=proposal.id, action="proposal_retargeted", actor="system", before_snapshot=before, after_snapshot=proposal.proposed_snapshot, reason=f"Proposed new topic “{name}” matches the published topic {topic.name}; converted to an update."))
                keepers[topic.id] = proposal
                report.add("topic: new topic -> update of a published topic", f"{name} -> {topic.name}")
            else:
                _absorb(db, keeper, proposal, alias=name)
                report.add("topic: new topic merged into the published topic's open update", f"{name} -> {topic.name} (proposal {keeper.id})")
            continue
        twin, score = best_match(name, new_keepers, lambda item: [item.proposed_snapshot.get("name", ""), *item.proposed_snapshot.get("aliases", [])])
        if twin is not None and score >= STRONG_MATCH:
            _absorb(db, twin, proposal, alias=name)
            report.add("topic: duplicate new topic merged into an earlier new topic", f"{name} -> {twin.proposed_snapshot.get('name')} ({score:.2f})")
            continue
        new_keepers.append(proposal)


def run(db: Session, *, apply: bool = False) -> Report:
    report = Report()
    consolidate_skills(db, report)
    consolidate_topics(db, report)
    if apply:
        db.commit()
    else:
        db.rollback()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Consolidate duplicate skills and knowledge topics waiting for review.")
    parser.add_argument("--apply", action="store_true", help="write the changes (default is a dry run)")
    args = parser.parse_args()
    with SessionLocal() as db:
        report = run(db, apply=args.apply)
    print("\n".join(report.lines()))
    print("\nApplied." if args.apply else "\nDry run: nothing was written. Re-run with --apply to make these changes.")


if __name__ == "__main__":
    main()
