from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete, desc, select

from app.database import SessionLocal
from app.models import (
    CareerLevel,
    Competency,
    CompetencyCategory,
    DomainLevelExpectation,
    DraftEvidence,
    DraftExpectation,
    ExpectationSource,
    PublicationBatch,
    ResearchFinding,
    ResearchFindingDomain,
    ResearchFindingIndustry,
    ResearchSource,
    ResearchSubmission,
    ResearchSubmissionAudit,
    ReviewAudit,
    ReviewChange,
    SecurityDomain,
)
from app.submission_deletion import delete_submission

ADMIN_HEADERS = {"X-Admin-API-Key": "test-admin-key"}


@pytest.fixture(autouse=True)
def clean_deletion_fixtures():
    yield
    with SessionLocal() as db:
        source_ids = list(db.scalars(select(ResearchSource.id).where(ResearchSource.source_title.like("Deletion test %"))).all())
        submission_ids = list(db.scalars(select(ResearchSubmission.id).where(ResearchSubmission.source_id.in_(source_ids))).all()) if source_ids else []
        finding_ids = list(db.scalars(select(ResearchFinding.id).where(ResearchFinding.submission_id.in_(submission_ids))).all()) if submission_ids else []
        draft_ids = list(db.scalars(select(DraftExpectation.id).where(DraftExpectation.submission_id.in_(submission_ids))).all()) if submission_ids else []
        change_ids = list(db.scalars(select(ReviewChange.id).where(ReviewChange.submission_id.in_(submission_ids))).all()) if submission_ids else []
        expectation_ids = list(db.scalars(select(DomainLevelExpectation.id).where(DomainLevelExpectation.expectation_description.like("Published dependency %"))).all())
        if change_ids:
            db.execute(delete(ReviewAudit).where(ReviewAudit.change_id.in_(change_ids)))
            db.execute(delete(ReviewChange).where(ReviewChange.id.in_(change_ids)))
        if draft_ids:
            db.execute(delete(DraftEvidence).where(DraftEvidence.draft_id.in_(draft_ids)))
            db.execute(delete(DraftExpectation).where(DraftExpectation.id.in_(draft_ids)))
        if finding_ids:
            db.execute(delete(ResearchFindingDomain).where(ResearchFindingDomain.finding_id.in_(finding_ids)))
            db.execute(delete(ResearchFindingIndustry).where(ResearchFindingIndustry.finding_id.in_(finding_ids)))
            db.execute(delete(ResearchFinding).where(ResearchFinding.id.in_(finding_ids)))
        if submission_ids:
            db.execute(delete(PublicationBatch).where(PublicationBatch.submission_id.in_(submission_ids)))
            db.execute(delete(ResearchSubmissionAudit).where(ResearchSubmissionAudit.submission_id.in_(submission_ids)))
            db.execute(delete(ResearchSubmission).where(ResearchSubmission.id.in_(submission_ids)))
        if source_ids:
            db.execute(delete(ExpectationSource).where(ExpectationSource.source_id.in_(source_ids)))
            db.execute(delete(ResearchSource).where(ResearchSource.id.in_(source_ids)))
        if expectation_ids:
            db.execute(delete(ExpectationSource).where(ExpectationSource.expectation_id.in_(expectation_ids)))
            db.execute(delete(DomainLevelExpectation).where(DomainLevelExpectation.id.in_(expectation_ids)))
        db.commit()



def create_submission_graph(*, status="draft_ready", draft_status="draft", change_status="pending", published=False):
    with SessionLocal() as db:
        domain = db.scalar(select(SecurityDomain))
        level = db.scalar(select(CareerLevel))
        category = db.scalar(select(CompetencyCategory))
        competency = db.scalar(select(Competency))
        source = ResearchSource(
            source_type="pasted_text",
            source_url="about:blank",
            source_title=f"Deletion test {uuid4().hex}",
            notes="Deletion test metadata",
        )
        db.add(source)
        db.flush()
        submission = ResearchSubmission(
            source_id=source.id,
            source_type="pasted_text",
            content_sha256=uuid4().hex + uuid4().hex,
            content_size=32,
            status=status,
            model_provider="ollama",
            model_id="test-model",
            model_name="test-model",
        )
        db.add(submission)
        db.flush()
        finding = ResearchFinding(
            submission_id=submission.id,
            domain_id=domain.id,
            career_level_id=level.id,
            category_id=category.id,
            competency_id=competency.id,
            candidate_name=f"Deletion Finding {submission.id}",
            normalized_name=f"deletion-finding-{submission.id}",
            finding_type="technical-skills",
            technical_knowledge="Test knowledge",
            practical_capability="Test capability",
            responsibilities="Test responsibility",
            proficiency_level="advanced",
            importance="essential",
            evidence_excerpt="Test evidence excerpt",
            status="normalized",
        )
        db.add(finding)
        db.flush()
        db.add(ResearchFindingDomain(finding_id=finding.id, domain_id=domain.id))

        draft = DraftExpectation(
            submission_id=submission.id,
            domain_id=domain.id,
            career_level_id=level.id,
            competency_id=competency.id,
            expectation_description=f"Deletion expectation {submission.id}",
            proficiency_level="advanced",
            importance="essential",
            responsibility_type="design",
            status=draft_status,
        )
        db.add(draft)
        db.flush()
        db.add(DraftEvidence(draft_id=draft.id, source_id=source.id, supporting_excerpt="Draft-only evidence"))

        batch = None
        published_expectation_id = None
        if published:
            published_expectation = DomainLevelExpectation(
                domain_id=domain.id,
                career_level_id=level.id,
                competency_id=competency.id,
                expectation_description=f"Published dependency {submission.id}",
                proficiency_level="advanced",
                importance="essential",
                responsibility_type="design",
            )
            db.add(published_expectation)
            db.flush()
            published_expectation_id = published_expectation.id
            draft.published_expectation_id = published_expectation.id
            db.add(ExpectationSource(expectation_id=published_expectation.id, source_id=source.id, supporting_excerpt="Published evidence"))
            batch = PublicationBatch(submission_id=submission.id, status="published", created_by="administrator")
            db.add(batch)
            db.flush()
            change_status = "published"

        change = ReviewChange(
            submission_id=submission.id,
            finding_id=finding.id,
            draft_id=draft.id,
            change_type="new_expectation",
            status=change_status,
            original_snapshot={"competency": {"name": competency.name}},
            proposed_snapshot={"competency_name": competency.name, "evidence": [{"excerpt": "Test evidence excerpt"}]},
            version=1,
        )
        if batch is not None:
            change.publication_batch_id = batch.id
        db.add(change)
        db.flush()
        db.add(ReviewAudit(change_id=change.id, action="created", actor="system", note="Deletion test"))
        db.commit()
        return {
            "submission_id": submission.id,
            "source_id": source.id,
            "finding_id": finding.id,
            "draft_id": draft.id,
            "change_id": change.id,
            "batch_id": batch.id if batch else None,
            "competency_id": competency.id,
            "published_expectation_id": published_expectation_id,
            "domain_id": domain.id,
            "level_id": level.id,
        }


def count_rows(ids):
    with SessionLocal() as db:
        return {
            "submission": db.get(ResearchSubmission, ids["submission_id"]),
            "source": db.get(ResearchSource, ids["source_id"]),
            "finding": db.get(ResearchFinding, ids["finding_id"]),
            "draft": db.get(DraftExpectation, ids["draft_id"]),
            "evidence": db.scalar(select(DraftEvidence).where(DraftEvidence.draft_id == ids["draft_id"])),
            "change": db.get(ReviewChange, ids["change_id"]),
            "audit": db.scalar(select(ReviewAudit).where(ReviewAudit.change_id == ids["change_id"])),
        }


@pytest.mark.parametrize(
    ("status", "draft_status", "change_status"),
    [
        ("draft_ready", "draft", "pending"),
        ("failed", "draft", "pending"),
        ("draft_ready", "rejected", "rejected"),
        ("draft_ready", "approved", "accepted"),
    ],
)
def test_delete_eligible_submission_removes_unpublished_graph(client, status, draft_status, change_status):
    ids = create_submission_graph(status=status, draft_status=draft_status, change_status=change_status)

    response = client.delete(f"/api/v1/research/submissions/{ids['submission_id']}", headers=ADMIN_HEADERS)

    assert response.status_code == 204
    rows = count_rows(ids)
    assert all(rows[key] is None for key in ("submission", "source", "finding", "draft", "evidence", "change", "audit"))
    with SessionLocal() as db:
        audit = db.scalar(select(ResearchSubmissionAudit).where(ResearchSubmissionAudit.submission_id == ids["submission_id"]).order_by(desc(ResearchSubmissionAudit.created_at), desc(ResearchSubmissionAudit.id)))
        assert audit is not None
        assert (audit.action, audit.actor, audit.previous_status) == ("deleted", "administrator", status)


def test_delete_requires_authentication_and_valid_identifier(client):
    assert client.delete("/api/v1/research/submissions/999999").status_code == 401
    assert client.delete("/api/v1/research/submissions/0", headers=ADMIN_HEADERS).status_code == 422
    assert client.delete("/api/v1/research/submissions/999999", headers=ADMIN_HEADERS).status_code == 404


def test_published_submission_is_protected_and_published_evidence_survives(client):
    ids = create_submission_graph(published=True, draft_status="published")

    response = client.delete(f"/api/v1/research/submissions/{ids['submission_id']}", headers=ADMIN_HEADERS)

    assert response.status_code == 409
    assert "published" in response.json()["detail"].lower()
    with SessionLocal() as db:
        assert db.get(ResearchSubmission, ids["submission_id"]) is not None
        assert db.get(DomainLevelExpectation, ids["published_expectation_id"]) is not None
        assert db.scalar(select(ExpectationSource).where(ExpectationSource.source_id == ids["source_id"])) is not None
        assert db.get(ResearchFinding, ids["finding_id"]) is not None


@pytest.mark.parametrize("status", ["received", "processing"])
def test_processing_submission_is_protected(client, status):
    ids = create_submission_graph(status=status)

    response = client.delete(f"/api/v1/research/submissions/{ids['submission_id']}", headers=ADMIN_HEADERS)

    assert response.status_code == 409
    assert "still being processed" in response.json()["detail"]
    assert count_rows(ids)["submission"] is not None


def test_deletion_preserves_unrelated_research_data(client):
    target = create_submission_graph()
    unrelated = create_submission_graph(status="failed")

    assert client.delete(f"/api/v1/research/submissions/{target['submission_id']}", headers=ADMIN_HEADERS).status_code == 204
    rows = count_rows(unrelated)
    assert all(rows[key] is not None for key in ("submission", "source", "finding", "draft", "evidence", "change", "audit"))


def test_deletion_preserves_evidence_shared_with_another_submission(client):
    target = create_submission_graph()
    unrelated = create_submission_graph(status="failed")
    with SessionLocal() as db:
        target_source_evidence = db.scalar(select(DraftEvidence).where(DraftEvidence.draft_id == target["draft_id"]))
        other_evidence = db.scalar(select(DraftEvidence).where(DraftEvidence.draft_id == unrelated["draft_id"]))
        other_evidence.source_id = target_source_evidence.source_id
        db.commit()

    assert client.delete(f"/api/v1/research/submissions/{target['submission_id']}", headers=ADMIN_HEADERS).status_code == 204
    with SessionLocal() as db:
        assert db.get(ResearchSource, target["source_id"]) is not None
        preserved = db.scalar(select(DraftEvidence).where(DraftEvidence.draft_id == unrelated["draft_id"]))
        assert preserved is not None
        assert preserved.source_id == target["source_id"]


def test_deletion_rolls_back_all_changes_when_cleanup_fails(monkeypatch):
    ids = create_submission_graph()
    with SessionLocal() as db:
        db.execute(delete(ResearchSubmissionAudit).where(ResearchSubmissionAudit.submission_id == ids["submission_id"]))
        db.commit()
    with SessionLocal() as db:
        original_flush = db.flush

        def fail_flush(*args, **kwargs):
            raise RuntimeError("simulated cleanup failure")

        monkeypatch.setattr(db, "flush", fail_flush)
        with pytest.raises(RuntimeError, match="simulated cleanup failure"):
            delete_submission(db, ids["submission_id"], "administrator")
        monkeypatch.setattr(db, "flush", original_flush)

    rows = count_rows(ids)
    assert all(rows[key] is not None for key in ("submission", "source", "finding", "draft", "evidence", "change", "audit"))
    with SessionLocal() as db:
        assert db.scalar(select(ResearchSubmissionAudit).where(ResearchSubmissionAudit.submission_id == ids["submission_id"])) is None
