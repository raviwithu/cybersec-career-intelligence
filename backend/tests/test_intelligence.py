from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.intelligence_service import dashboard, evidence, gap_analysis, get_profile, new_profile, progression, save_assessments, trends
from app.models import Competency, DomainLevelExpectation, ExpectationSource, Industry, ResearchSource, SecurityDomain, CareerLevel
from app.seed import seed_reference_data


@pytest.fixture
def intelligence_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        seed_reference_data(db)
        automotive = db.scalar(select(Industry).where(Industry.slug == "automotive"))
        medical = db.scalar(select(Industry).where(Industry.slug == "medical-devices-healthcare-technology"))
        boot = db.scalar(select(SecurityDomain).where(SecurityDomain.slug == "boot-security"))
        embedded = db.scalar(select(SecurityDomain).where(SecurityDomain.slug == "embedded-systems-security"))
        architect = db.scalar(select(CareerLevel).where(CareerLevel.slug == "architect"))
        senior = db.scalar(select(CareerLevel).where(CareerLevel.slug == "senior"))
        secure_boot = db.scalar(select(Competency).where(Competency.slug == "secure-boot"))
        api_auth = db.scalar(select(Competency).where(Competency.slug == "api-authorization"))
        sources = [ResearchSource(source_type="published_report", source_url=f"https://research.example/{index}", source_title=f"Published report {index}", collected_at=datetime(2026, index, 15, tzinfo=timezone.utc)) for index in (1, 2, 3)]
        db.add_all(sources)
        db.flush()
        automotive_expectations = [
            DomainLevelExpectation(domain_id=boot.id, career_level_id=senior.id, competency_id=secure_boot.id, industry_id=automotive.id, expectation_description="Secure embedded boot at senior level.", proficiency_level="advanced", importance="important", responsibility_type="execution"),
            DomainLevelExpectation(domain_id=boot.id, career_level_id=architect.id, competency_id=secure_boot.id, industry_id=automotive.id, expectation_description="Design embedded boot architecture.", proficiency_level="expert", importance="essential", responsibility_type="design"),
            DomainLevelExpectation(domain_id=boot.id, career_level_id=architect.id, competency_id=api_auth.id, industry_id=automotive.id, expectation_description="Apply API controls to connected devices.", proficiency_level="advanced", importance="important", responsibility_type="design"),
            DomainLevelExpectation(domain_id=embedded.id, career_level_id=architect.id, competency_id=api_auth.id, industry_id=medical.id, expectation_description="Protect connected device APIs.", proficiency_level="advanced", importance="important", responsibility_type="design"),
        ]
        db.add_all(automotive_expectations)
        db.flush()
        # Two expectations are linked to one source to verify source-level deduplication.
        db.add_all([
            ExpectationSource(expectation_id=automotive_expectations[0].id, source_id=sources[0].id, supporting_excerpt="Senior secure boot evidence."),
            ExpectationSource(expectation_id=automotive_expectations[1].id, source_id=sources[0].id, supporting_excerpt="Architect secure boot evidence."),
            ExpectationSource(expectation_id=automotive_expectations[1].id, source_id=sources[1].id, supporting_excerpt="Second architect source."),
            ExpectationSource(expectation_id=automotive_expectations[2].id, source_id=sources[1].id, supporting_excerpt="Automotive API evidence."),
            ExpectationSource(expectation_id=automotive_expectations[3].id, source_id=sources[2].id, supporting_excerpt="Medical device API evidence."),
        ])
        db.commit()
        yield db, {"automotive": automotive, "medical": medical, "boot": boot, "embedded": embedded, "architect": architect, "senior": senior, "secure_boot": secure_boot, "api_auth": api_auth}
    engine.dispose()


def test_frequency_uses_distinct_sources_and_excludes_source_less_seed(intelligence_db):
    db, taxonomy = intelligence_db
    result = dashboard(db, industry="automotive", domain="boot-security", career_level="architect")
    assert result.relevant_source_count == 2
    assert result.distinct_competency_count == 2
    item = result.competency_frequency[0]
    assert item.source_count == 2
    assert item.mention_rate == 100.0
    assert any("source-less illustrative" in warning for warning in result.data_quality) is False


def test_dashboard_filters_and_progression_keep_tracks_explicit(intelligence_db):
    db, taxonomy = intelligence_db
    filtered = dashboard(db, industry="medical-devices-healthcare-technology", domain="embedded-systems-security", career_level="architect")
    assert filtered.relevant_source_count == 1
    assert filtered.competency_frequency[0].competency.slug == "api-authorization"
    result = progression(db, industry="automotive", domain="boot-security", starting_level="senior", target_level="architect")
    assert result.starting_level.slug == "senior"
    assert result.target_level.slug == "architect"
    assert result.target_additional_expectations
    assert result.technical_track == "shared → technical"
    assert any("Missing evidence" in warning for warning in result.warnings)


def test_trends_report_insufficient_sample_size(intelligence_db):
    db, _ = intelligence_db
    result = trends(db, window="monthly", industry="automotive", domain="boot-security", career_level="architect", date_from=None, date_to=None, minimum_sample_size=3, minimum_coverage=3)
    assert result.relevant_source_count == 2
    assert result.trends[0].direction == "insufficient_data"
    assert result.trends[0].warning
    assert "not representative" in result.data_quality[1]


def test_evidence_explorer_returns_supporting_excerpt(intelligence_db):
    db, taxonomy = intelligence_db
    result = evidence(db, competency_id=taxonomy["secure_boot"].id, industry="automotive", domain="boot-security", career_level="architect", date_from=None, date_to=None, limit=10)
    assert result.total == 2
    assert {item.source_title for item in result.evidence} == {"Published report 1", "Published report 2"}
    assert all(item.excerpt for item in result.evidence)


def test_private_profile_key_and_unassessed_gap_semantics(intelligence_db):
    db, taxonomy = intelligence_db
    profile, profile_key = new_profile(db, target_industry_id=taxonomy["automotive"].id, target_domain_id=taxonomy["boot"].id, target_career_level_id=taxonomy["architect"].id)
    with pytest.raises(Exception):
        get_profile(db, "wrong-key")
    assert get_profile(db, profile_key).id == profile.id
    save_assessments(db, profile, [{"competency_id": taxonomy["secure_boot"].id, "proficiency": "advanced"}])
    result = gap_analysis(db, get_profile(db, profile_key))
    assert result.assessed_competency_count == 1
    assert result.unassessed
    assert any("not treated as a missing skill" in warning for warning in result.warnings)


def test_phase7_api_dashboard_profile_auth_and_grounded_ask(client):
    dashboard_response = client.get("/api/v1/intelligence/dashboard")
    assert dashboard_response.status_code == 200
    dashboard_body = dashboard_response.json()
    assert {"relevant_source_count", "coverage", "data_quality"} <= dashboard_body.keys()

    created = client.post("/api/v1/intelligence/profiles", json={})
    assert created.status_code == 201
    profile_key = created.json()["profile_key"]
    assert len(profile_key) >= 32
    assert client.get("/api/v1/intelligence/profiles/me").status_code == 401
    profile = client.get("/api/v1/intelligence/profiles/me", headers={"X-Profile-Key": profile_key})
    assert profile.status_code == 200
    assert "profile_key" not in profile.json()

    ask = client.post("/api/v1/intelligence/ask", json={"question": "What evidence supports secure boot?"})
    assert ask.status_code == 200
    assert ask.json()["insufficient_evidence"] is True
    assert ask.json()["evidence"] == []
