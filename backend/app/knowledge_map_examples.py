"""Submit the KM-5 example knowledge map content as proposals. Run manually; never from startup or seed.py.

    python -m app.knowledge_map_examples              # example topics, placements, sections, levels, relationships
    python -m app.knowledge_map_examples --dry-run    # print what would be proposed
    python -m app.knowledge_map_examples --place-existing   # also propose branches for existing unplaced topics

Everything is a proposal (source_type "manual") with a stable idempotency key, so the script is safe to re-run:
proposals that already exist are reported, not duplicated, and nothing is published. Topics that do not exist yet are
proposed with CREATE_TOPIC (with their placements); once an administrator publishes those, run the script again to
propose their sections, career levels and relationships. Existing topics are reused, and sections they already have
are never replaced.
"""
from __future__ import annotations

import argparse
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .database import SessionLocal
from .knowledge_contract_schemas import KnowledgeProposalCreate
from .knowledge_contract_service import _client_idempotency_key, create_proposal
from .knowledge_map_example_content import EXAMPLE_NOTES, EXAMPLE_TOPICS, EXISTING_FOUNDATIONS, EXISTING_UNLINKED, LEVEL_SLUGS
from .knowledge_map_proposals import find_duplicate_topic
from .models import CareerLevel, KnowledgeTopic, KnowledgeTopicDomain, KnowledgeTopicProposal, KnowledgeTopicRelationship, SecurityDomain

ACTOR = "administrator"
SECTION_ORDER = ("overview", "how_it_works", "code_examples", "attack_surfaces", "mitigations", "real_world_examples", "architecture", "references")


class Runner:
    def __init__(self, db: Session, *, dry_run: bool = False):
        self.db = db
        self.dry_run = dry_run
        self.log: list[str] = []
        self.created = 0
        self.existing = 0
        self.domains = {domain.slug: domain for domain in db.scalars(select(SecurityDomain).where(SecurityDomain.is_active.is_(True))).all()}
        self.levels = {level.slug: level for level in db.scalars(select(CareerLevel).where(CareerLevel.is_active.is_(True))).all()}

    def submit(self, key: str, payload: dict[str, Any], label: str) -> None:
        scoped = _client_idempotency_key(ACTOR, key)
        if self.db.scalar(select(KnowledgeTopicProposal.id).where(KnowledgeTopicProposal.idempotency_key == scoped)) is not None:
            self.existing += 1
            self.log.append(f"exists   {label}")
            return
        if self.dry_run:
            self.log.append(f"would    {label}")
            return
        try:
            proposal = create_proposal(self.db, KnowledgeProposalCreate.model_validate({"schema_version": "1.0", "source_type": "manual", "submit_for_review": True, **payload}), ACTOR, key)
        except HTTPException as exc:
            self.db.rollback()
            detail = exc.detail if isinstance(exc.detail, str) else exc.detail.get("message", str(exc.detail))
            self.log.append(f"skipped  {label}: {detail}")
            return
        self.created += 1
        self.log.append(f"proposed {label} (#{proposal.id})")

    def placements(self, spec: dict) -> list[dict[str, Any]]:
        result = []
        for slug, branch in spec["placements"]:
            domain = self.domains.get(slug)
            if domain is None:
                self.log.append(f"missing  domain {slug} for {spec['name']}; placement not proposed")
                continue
            result.append({"domain_id": domain.id, "map_branch": branch})
        return result

    def topic(self, key: str) -> KnowledgeTopic | None:
        return self.db.scalar(select(KnowledgeTopic).options(selectinload(KnowledgeTopic.sections), selectinload(KnowledgeTopic.level_expectations), selectinload(KnowledgeTopic.domains)).where((KnowledgeTopic.topic_key == key) | (KnowledgeTopic.slug == key)))

    def example(self, spec: dict) -> None:
        key = spec["topic_key"]
        note = EXAMPLE_NOTES.get(key, "")
        existing = self.topic(key) or find_duplicate_topic(self.db, [spec["name"], key, *spec["aliases"]])
        if existing is None:
            self.submit(f"km5:{key}:create", {
                "action": "CREATE_TOPIC", "topic_name": spec["name"], "topic_key": key,
                "proposed_content": {"topic": {"name": spec["name"], "description": spec["description"], "aliases": spec["aliases"]}, "placements": self.placements(spec)},
                "change_reason": f"KM-5 example topic. Sections, career levels and relationships follow after this topic is published (run the script again). {note}".strip(),
                "references": spec["references"][:3],
            }, f"CREATE_TOPIC {spec['name']}")
            return
        topic = self.topic(existing.topic_key or existing.slug) or existing
        if topic.topic_key != key:
            self.log.append(f"reuse    {spec['name']} -> existing topic {topic.name} ({topic.topic_key})")
        placed = {(link.domain_id, link.map_branch) for link in topic.domains}
        for placement in self.placements(spec):
            if (placement["domain_id"], placement["map_branch"]) in placed:
                continue
            self.submit(f"km5:{key}:place:{placement['domain_id']}", {"action": "PLACE_TOPIC", "topic_id": topic.id, "proposed_content": placement, "change_reason": "KM-5 example placement."}, f"PLACE_TOPIC {topic.name} in domain {placement['domain_id']} ({placement['map_branch']})")
        have = {section.section_type for section in topic.sections}
        for section_type in SECTION_ORDER:
            content = spec["sections"].get(section_type)
            if section_type == "references":
                content = {"items": spec["references"]}
            if not content:
                continue
            if section_type in have:
                self.log.append(f"keep     {topic.name}: existing {section_type} section is not replaced")
                continue
            reason = f"KM-5 example {section_type.replace('_', ' ')} for {topic.name}. References are unverified until an administrator verifies them."
            if section_type == "real_world_examples":
                reason += " " + note
            self.submit(f"km5:{key}:section:{section_type}", {"action": "ADD_SECTION", "topic_id": topic.id, "section": section_type, "proposed_content": content, "change_reason": reason[:500], "references": spec["references"][:5]}, f"ADD_SECTION {topic.name} {section_type}")
        if "real_world_examples" not in spec["sections"] and note:
            self.log.append(f"note     {topic.name}: {note}")
        self.levels_for(spec, topic)
        for target_key, relationship_type in spec["relationships"]:
            target = self.topic(target_key)
            if target is None:
                self.log.append(f"later    {topic.name} {relationship_type} {target_key}: target topic not published yet")
                continue
            if self.db.scalar(select(KnowledgeTopicRelationship.id).where(KnowledgeTopicRelationship.source_topic_id == topic.id, KnowledgeTopicRelationship.target_topic_id == target.id, KnowledgeTopicRelationship.relationship_type == relationship_type)):
                continue
            self.submit(f"km5:{key}:rel:{relationship_type}:{target_key}", {"action": "ADD_TOPIC_RELATIONSHIP", "topic_id": topic.id, "proposed_content": {"target_topic_id": target.id, "relationship_type": relationship_type}, "change_reason": "KM-5 example relationship."}, f"ADD_TOPIC_RELATIONSHIP {topic.name} {relationship_type} {target.name}")

    def levels_for(self, spec: dict, topic: KnowledgeTopic) -> None:
        existing = {(row.career_level_id, row.industry_id) for row in topic.level_expectations}
        rows = []
        for slug in LEVEL_SLUGS:
            level = self.levels.get(slug)
            if level is None or (level.id, None) in existing or slug not in spec["levels"]:
                continue
            knowledge, practical = spec["levels"][slug]
            rows.append({"career_level_id": level.id, "industry_id": None, "expectation": knowledge, "practical_capability": practical})
        if rows:
            self.submit(f"km5:{spec['topic_key']}:levels", {"action": "UPDATE_CAREER_LEVELS", "topic_id": topic.id, "proposed_content": {"levels": rows}, "change_reason": "KM-5 example career-level expectations; existing level rows are left unchanged."}, f"UPDATE_CAREER_LEVELS {topic.name} ({len(rows)} levels)")

    def place_existing(self) -> None:
        examples = {spec["topic_key"] for spec in EXAMPLE_TOPICS}
        topics = self.db.scalars(select(KnowledgeTopic).options(selectinload(KnowledgeTopic.domains)).where(KnowledgeTopic.is_active.is_(True), KnowledgeTopic.publication_status == "published").order_by(KnowledgeTopic.id)).all()
        for topic in topics:
            key = topic.topic_key or topic.slug
            if key in examples or any(link.map_branch for link in topic.domains):
                continue
            branch = "foundations" if key in EXISTING_FOUNDATIONS else "security"
            domain_ids = [link.domain_id for link in topic.domains] or [self.domains[slug].id for slug in EXISTING_UNLINKED.get(key, []) if slug in self.domains]
            if not domain_ids:
                self.log.append(f"skip     {topic.name}: no domain link to place it in")
            for domain_id in domain_ids:
                self.submit(f"km5:existing:{key}:{domain_id}", {"action": "PLACE_TOPIC", "topic_id": topic.id, "proposed_content": {"domain_id": domain_id, "map_branch": branch}, "change_reason": f"KM-5 proposed branch for an existing topic: {branch}, based on its current domain links."}, f"PLACE_TOPIC {topic.name} in domain {domain_id} ({branch})")


def run(db: Session, *, dry_run: bool = False, place_existing: bool = False) -> Runner:
    runner = Runner(db, dry_run=dry_run)
    for spec in EXAMPLE_TOPICS:
        runner.example(spec)
    if place_existing:
        runner.place_existing()
    return runner


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit KM-5 example knowledge map content as proposals (nothing is published).")
    parser.add_argument("--dry-run", action="store_true", help="show what would be proposed without writing")
    parser.add_argument("--place-existing", action="store_true", help="also propose branches for existing unplaced topics")
    args = parser.parse_args()
    with SessionLocal() as db:
        runner = run(db, dry_run=args.dry_run, place_existing=args.place_existing)
    print("\n".join(runner.log))
    print(f"\n{runner.created} proposals created, {runner.existing} already existed. Review them in Knowledge Review > Mind Map Changes.")


if __name__ == "__main__":
    main()
