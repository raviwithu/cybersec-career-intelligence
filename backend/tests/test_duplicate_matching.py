from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, func, select

from app.config import get_settings
from app.database import SessionLocal
from app.duplicate_consolidation import run as consolidate_backlog
from app.knowledge_topic_schemas import TopicProposalReview
from app.knowledge_topic_service import publish_topics, review_proposal
from app.models import (
    Competency,
    CompetencyCategory,
    DomainLevelExpectation,
    KnowledgeTopic,
    KnowledgeTopicEvidence,
    KnowledgeTopicProposal,
    ResearchFinding,
    ResearchSource,
    ResearchSubmission,
    ReviewChange,
)
from app.name_matching import STRONG_MATCH, similarity
from app.phase5_schemas import ExtractedRequirement, ExtractionResult
from app.phase5_service import process_submission, taxonomy
from app.research_review_service import accept_change


@pytest.fixture(autouse=True)
def _remove_created_rows(client):
    # Shared test database: remove what each test adds (SQLite reuses deleted ids).
    with SessionLocal() as db:
        marks = {model: db.scalar(select(func.max(model.id))) or 0 for model in (ResearchSource, ResearchSubmission, KnowledgeTopicProposal, KnowledgeTopic, Competency, DomainLevelExpectation)}
    yield
    with SessionLocal() as db:
        for model in (KnowledgeTopicProposal, ResearchSubmission, ResearchSource, DomainLevelExpectation, KnowledgeTopic, Competency):
            db.execute(delete(model).where(model.id > marks[model]))
        db.commit()


class FakeExtractor:
    model = "fake-model"

    def __init__(self, names: list[tuple[str, str, str]]):
        self.names = names
        self.taxonomies: list[dict] = []

    def extract(self, content, taxonomy, model=None):
        self.taxonomies.append(taxonomy)
        return ExtractionResult(requirements=[ExtractedRequirement(competency_name=name, domain_slugs=[domain], career_level=level, category_slug="technical-skills", technical_knowledge=f"Knows {name}.", practical_capability=f"Performs {name}.", evidence_excerpt=f"The role requires {name}.", confidence=0.9) for name, domain, level in self.names])


def ingest(db, names: list[tuple[str, str, str]]) -> tuple[ResearchSubmission, FakeExtractor]:
    source = ResearchSource(source_type="jsearch", source_url=f"https://jobs.example/{uuid.uuid4().hex}", source_title="Security role", collected_at=datetime.now(timezone.utc))
    submission = ResearchSubmission(source=source, source_type="jsearch", content_sha256=uuid.uuid4().hex * 2, content_size=100, status="received", model_provider="ollama", model_id="fake-model")
    db.add(submission)
    db.commit()
    extractor = FakeExtractor(names)
    process_submission(db, submission, "A job posting.", extractor, get_settings())
    return submission, extractor


def findings_of(db, submission) -> list[ResearchFinding]:
    return list(db.scalars(select(ResearchFinding).where(ResearchFinding.submission_id == submission.id).order_by(ResearchFinding.id)).all())


def change_of(db, finding) -> ReviewChange:
    return db.scalar(select(ReviewChange).where(ReviewChange.finding_id == finding.id))


def test_similarity_treats_rewordings_as_the_same_and_keeps_distinct_skills_apart():
    same = [("Incident Response", "Security incident response"), ("Experience with API authorization", "API Authorization"), ("Cyber forensic and intrusion analysis", "Cyber forensics and intrusion analysis"), ("DFIR", "Digital forensics and incident response"), ("Cloud security skills", "Cloud Security"), ("Leading security engineering programs", "Security engineering program leadership")]
    different = [("Security team leadership and mentoring", "Cybersecurity deal-team leadership and mentoring"), ("Digital forensics and incident response", "Host forensic analysis"), ("Threat Modeling", "Threat hunting"), ("Container Security", "Kubernetes Security")]
    for left, right in same:
        assert similarity(left, right) >= STRONG_MATCH, (left, right, similarity(left, right))
    for left, right in different:
        assert similarity(left, right) < STRONG_MATCH, (left, right, similarity(left, right))


def test_ingestion_reuses_published_skills_and_skills_awaiting_review():
    with SessionLocal() as db:
        api = db.scalar(select(Competency).where(Competency.slug == "api-authorization"))
        first, _ = ingest(db, [("Experience with API authorization", "cloud-api-security", "senior"), ("Incident Response", "security-operations", "intermediate")])
        api_finding, ir_finding = findings_of(db, first)
        assert api_finding.competency_id == api.id
        assert api_finding.details["skill_match"]["method"] == "similar_published_skill"
        assert change_of(db, api_finding).change_type in {"new_expectation", "update_expectation"}
        first_ir = change_of(db, ir_finding)
        assert first_ir.change_type == "new_competency"

        second, extractor = ingest(db, [("Security Incident Response", "security-operations", "senior")])
        assert "Incident Response" in extractor.taxonomies[0]["proposed_competencies"]
        (finding,) = findings_of(db, second)
        change = change_of(db, finding)
        assert change.change_type == "new_competency"
        assert change.proposed_snapshot["competency_name"] == "Incident Response"
        assert change.proposed_snapshot["same_new_skill_as_change_id"] == first_ir.id
        assert finding.details["skill_match"]["method"] == "similar_pending_skill"
        assert "Incident Response" in taxonomy(db)["proposed_competencies"]


def test_findings_for_the_same_topic_join_one_open_proposal():
    with SessionLocal() as db:
        topic = db.scalar(select(KnowledgeTopic).where(KnowledgeTopic.topic_key == "kubernetes-security"))
        open_query = select(func.count()).select_from(KnowledgeTopicProposal).where(KnowledgeTopicProposal.topic_id == topic.id, KnowledgeTopicProposal.status == "review")
        first, _ = ingest(db, [("Kubernetes security", "cloud-infrastructure-security", "senior")])
        (first_finding,) = findings_of(db, first)
        open_after_first = db.scalar(open_query)
        second, _ = ingest(db, [("K8s security hardening experience", "cloud-infrastructure-security", "architect"), ("Kubernetes Security", "cloud-api-security", "junior")])
        assert db.scalar(open_query) == open_after_first
        proposal_id = db.scalar(select(KnowledgeTopicProposal.id).where(KnowledgeTopicProposal.finding_id == first_finding.id)) or first_finding.details.get("topic_proposal_id")
        for finding in findings_of(db, second):
            if finding.normalized_name == "Kubernetes Security":
                assert db.scalar(select(KnowledgeTopicProposal.id).where(KnowledgeTopicProposal.finding_id == finding.id)) is None
                assert finding.details["topic_proposal_id"] == proposal_id
        proposal = db.get(KnowledgeTopicProposal, proposal_id)
        assert db.scalar(select(func.count()).select_from(KnowledgeTopicEvidence).where(KnowledgeTopicEvidence.proposal_id == proposal.id)) >= 2


def test_similar_new_topics_share_one_proposal_with_an_alias():
    with SessionLocal() as db:
        first, _ = ingest(db, [("Host forensic analysis", "security-operations", "senior")])
        second, _ = ingest(db, [("Forensic analysis of hosts", "security-operations", "intermediate")])
        proposals = db.scalars(select(KnowledgeTopicProposal).where(KnowledgeTopicProposal.proposal_type == "new_topic", KnowledgeTopicProposal.status == "review", func.lower(KnowledgeTopicProposal.proposed_snapshot["name"].as_string()).like("host forensic%"))).all()
        assert len(proposals) == 1
        assert proposals[0].proposed_snapshot["aliases"] == ["Forensic analysis of hosts"]
        assert {item["career_level_id"] for item in proposals[0].proposed_snapshot["level_expectations"]} >= {findings_of(db, first)[0].career_level_id, findings_of(db, second)[0].career_level_id}


def test_publishing_never_creates_a_duplicate_skill_or_topic():
    with SessionLocal() as db:
        submission, _ = ingest(db, [("Cloud Detection Engineering", "cloud-api-security", "senior")])
        (finding,) = findings_of(db, submission)
        change = change_of(db, finding)
        assert change.change_type == "new_competency"
        topic_proposal = db.scalar(select(KnowledgeTopicProposal).where(KnowledgeTopicProposal.finding_id == finding.id))
        assert topic_proposal.proposal_type == "new_topic"
        # Meanwhile the same skill and topic were published under slightly different names.
        category = db.scalar(select(CompetencyCategory).where(CompetencyCategory.slug == "technical-skills"))
        existing = Competency(name="Cloud detection engineering skills", slug=f"cloud-detection-{uuid.uuid4().hex[:6]}", description="", category_id=category.id)
        topic = KnowledgeTopic(name="Cloud Detection Engineering Experience", slug=f"cloud-detection-{uuid.uuid4().hex[:6]}", topic_key=f"cloud-detection-{uuid.uuid4().hex[:6]}", publication_status="published", is_active=True, version=1, aliases=[])
        db.add_all([existing, topic])
        db.commit()
        competencies_before = db.scalar(select(func.count()).select_from(Competency))
        topics_before = db.scalar(select(func.count()).select_from(KnowledgeTopic))

        accept_change(db, change.id, change.version, "administrator", "Approve.", publish=True)
        db.refresh(change)
        assert change.status == "published" and change.target_competency_id == existing.id
        assert db.scalar(select(func.count()).select_from(Competency)) == competencies_before

        reviewed = review_proposal(db, topic_proposal.id, TopicProposalReview(expected_version=topic_proposal.version, action="accept"), "administrator")
        publish_topics(db, [reviewed.id], None, {reviewed.id: reviewed.version}, "administrator", "Publish.")
        db.expire_all()
        assert db.scalar(select(func.count()).select_from(KnowledgeTopic)) == topics_before
        topic = db.get(KnowledgeTopic, topic.id)
        assert topic.is_active and "Cloud Detection Engineering" in topic.aliases
        assert db.get(KnowledgeTopicProposal, reviewed.id).topic_id == topic.id


def test_backlog_consolidation_is_a_dry_run_by_default_and_idempotent():
    with SessionLocal() as db:
        topic = db.scalar(select(KnowledgeTopic).where(KnowledgeTopic.topic_key == "container-security"))
        names = ("Supply chain artifact signing", "Signing of supply-chain artifacts", "Supply chain artifact signing")
        created = []
        for index, name in enumerate([*names, None, None]):
            content = {"name": name, "domain_ids": [], "industry_ids": [], "aliases": [], "level_expectations": [], "related_competency_ids": []} if name else {"name": topic.name, "domain_ids": [index], "industry_ids": [], "aliases": [], "level_expectations": [], "related_competency_ids": []}
            proposal = KnowledgeTopicProposal(topic_id=None if name else topic.id, proposal_type="new_topic" if name else "topic_update", status="review", fingerprint=uuid.uuid4().hex, proposed_snapshot=content, version=1, contract="legacy")
            db.add(proposal)
            created.append(proposal)
        db.commit()
        ids = [item.id for item in created]

        report = consolidate_backlog(db)
        assert report.counts["topic: duplicate new topic merged into an earlier new topic"] >= 1
        assert {db.get(KnowledgeTopicProposal, item).status for item in ids} == {"review"}

        consolidate_backlog(db, apply=True)
        db.expire_all()
        statuses = [db.get(KnowledgeTopicProposal, item).status for item in ids]
        assert statuses.count("merged") >= 3
        keeper = db.get(KnowledgeTopicProposal, ids[0])
        assert keeper.status == "review" and keeper.proposed_snapshot["aliases"] == ["Signing of supply-chain artifacts"]
        again = consolidate_backlog(db, apply=True)
        assert not any(kind.startswith("topic:") for kind in again.counts)
