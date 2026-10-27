from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CareerProfile(Base):
    __tablename__ = "career_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    target_role: Mapped[str] = mapped_column(String(160))
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SecurityDomain(Base):
    __tablename__ = "security_domains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("security_domains.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    slug: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    parent: Mapped["SecurityDomain | None"] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list["SecurityDomain"]] = relationship(back_populates="parent", cascade="all, delete-orphan")
    expectations: Mapped[list["DomainLevelExpectation"]] = relationship(back_populates="domain")


class CareerLevel(Base):
    __tablename__ = "career_levels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    career_track: Mapped[str] = mapped_column(String(30), default="shared")
    description: Mapped[str] = mapped_column(Text, default="")
    display_order: Mapped[int] = mapped_column(Integer, default=0)

    expectations: Mapped[list["DomainLevelExpectation"]] = relationship(back_populates="career_level")


class CompetencyCategory(Base):
    __tablename__ = "competency_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")

    competencies: Mapped[list["Competency"]] = relationship(back_populates="category")


class Competency(Base):
    __tablename__ = "competencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category_id: Mapped[int] = mapped_column(ForeignKey("competency_categories.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    category: Mapped[CompetencyCategory] = relationship(back_populates="competencies")
    expectations: Mapped[list["DomainLevelExpectation"]] = relationship(back_populates="competency")
    source_relationships: Mapped[list["CompetencyRelationship"]] = relationship(
        foreign_keys="CompetencyRelationship.source_competency_id", back_populates="source_competency", cascade="all, delete-orphan"
    )
    target_relationships: Mapped[list["CompetencyRelationship"]] = relationship(
        foreign_keys="CompetencyRelationship.target_competency_id", back_populates="target_competency", cascade="all, delete-orphan"
    )


class DomainLevelExpectation(Base):
    __tablename__ = "domain_level_expectations"
    __table_args__ = (
        CheckConstraint("experience_years_min IS NULL OR experience_years_min >= 0", name="ck_expectation_min_years_nonnegative"),
        CheckConstraint("experience_years_max IS NULL OR experience_years_max >= 0", name="ck_expectation_max_years_nonnegative"),
        CheckConstraint(
            "experience_years_min IS NULL OR experience_years_max IS NULL OR experience_years_min <= experience_years_max",
            name="ck_expectation_year_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("security_domains.id"), index=True)
    career_level_id: Mapped[int] = mapped_column(ForeignKey("career_levels.id"), index=True)
    competency_id: Mapped[int] = mapped_column(ForeignKey("competencies.id"), index=True)
    technical_knowledge: Mapped[str] = mapped_column(Text, default="")
    practical_capability: Mapped[str] = mapped_column(Text, default="")
    qualifications: Mapped[str] = mapped_column(Text, default="")
    tools_technologies: Mapped[str] = mapped_column(Text, default="")
    expectation_description: Mapped[str] = mapped_column(Text)
    proficiency_level: Mapped[str] = mapped_column(String(40))
    importance: Mapped[str] = mapped_column(String(40))
    responsibility_type: Mapped[str] = mapped_column(String(80))
    experience_years_min: Mapped[int | None] = mapped_column(Integer)
    experience_years_max: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    domain: Mapped[SecurityDomain] = relationship(back_populates="expectations")
    career_level: Mapped[CareerLevel] = relationship(back_populates="expectations")
    competency: Mapped[Competency] = relationship(back_populates="expectations")
    sources: Mapped[list["ExpectationSource"]] = relationship(back_populates="expectation", cascade="all, delete-orphan")


class CompetencyRelationship(Base):
    __tablename__ = "competency_relationships"
    __table_args__ = (
        UniqueConstraint("source_competency_id", "target_competency_id", "relationship_type", name="uq_competency_relationship"),
        CheckConstraint("relationship_type IN ('prerequisite', 'related', 'specialization', 'dependency')", name="ck_relationship_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_competency_id: Mapped[int] = mapped_column(ForeignKey("competencies.id", ondelete="CASCADE"), index=True)
    target_competency_id: Mapped[int] = mapped_column(ForeignKey("competencies.id", ondelete="CASCADE"), index=True)
    relationship_type: Mapped[str] = mapped_column(String(30))

    source_competency: Mapped[Competency] = relationship(foreign_keys=[source_competency_id], back_populates="source_relationships")
    target_competency: Mapped[Competency] = relationship(foreign_keys=[target_competency_id], back_populates="target_relationships")


class ResearchSource(Base):
    __tablename__ = "research_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(60))
    source_url: Mapped[str] = mapped_column(String(1000))
    source_title: Mapped[str] = mapped_column(String(300))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    notes: Mapped[str | None] = mapped_column(Text)

    expectations: Mapped[list["ExpectationSource"]] = relationship(back_populates="source", cascade="all, delete-orphan")


class ExpectationSource(Base):
    __tablename__ = "expectation_sources"

    expectation_id: Mapped[int] = mapped_column(ForeignKey("domain_level_expectations.id", ondelete="CASCADE"), primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("research_sources.id", ondelete="CASCADE"), primary_key=True)
    supporting_excerpt: Mapped[str] = mapped_column(Text)

    expectation: Mapped[DomainLevelExpectation] = relationship(back_populates="sources")
    source: Mapped[ResearchSource] = relationship(back_populates="expectations")


class AnalysisVersion(Base):
    __tablename__ = "analysis_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(80), unique=True)
    analysis_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    description: Mapped[str] = mapped_column(Text)
    methodology: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ModelSelection(Base):
    __tablename__ = "model_selection"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    selected_provider: Mapped[str] = mapped_column(String(30), default="ollama")
    selected_model: Mapped[str | None] = mapped_column(String(255))
    mode: Mapped[str] = mapped_column(String(20), default="fallback")
    evaluation_version: Mapped[str | None] = mapped_column(String(80))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ModelEvaluation(Base):
    __tablename__ = "model_evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    evaluation_version: Mapped[str] = mapped_column(String(80), index=True)
    provider: Mapped[str] = mapped_column(String(30), default="ollama", index=True)
    model_id: Mapped[str] = mapped_column(String(255), default="", index=True)
    model_name: Mapped[str] = mapped_column(String(255), index=True)
    extraction_accuracy: Mapped[float] = mapped_column(default=0.0)
    domain_accuracy: Mapped[float] = mapped_column(default=0.0)
    career_level_accuracy: Mapped[float] = mapped_column(default=0.0)
    classification_accuracy: Mapped[float] = mapped_column(default=0.0)
    json_validity: Mapped[float] = mapped_column(default=0.0)
    hallucination_rate: Mapped[float] = mapped_column(default=0.0)
    average_processing_ms: Mapped[float] = mapped_column(default=0.0)
    overall_score: Mapped[float] = mapped_column(default=0.0, index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ResearchSubmission(Base):
    __tablename__ = "research_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("research_sources.id", ondelete="CASCADE"), unique=True, index=True)
    source_type: Mapped[str] = mapped_column(String(30))
    original_filename: Mapped[str | None] = mapped_column(String(255))
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    content_size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="received", index=True)
    extraction_payload: Mapped[dict | None] = mapped_column(JSON)
    model_provider: Mapped[str | None] = mapped_column(String(30))
    model_id: Mapped[str | None] = mapped_column(String(255))
    model_name: Mapped[str | None] = mapped_column(String(255))
    evaluation_version: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    source: Mapped[ResearchSource] = relationship()
    findings: Mapped[list["ResearchFinding"]] = relationship(back_populates="submission", cascade="all, delete-orphan")
    drafts: Mapped[list["DraftExpectation"]] = relationship(back_populates="submission")
    review_changes: Mapped[list["ReviewChange"]] = relationship(back_populates="submission", cascade="all, delete-orphan")
    publication_batches: Mapped[list["PublicationBatch"]] = relationship(back_populates="submission", cascade="all, delete-orphan")


class ResearchFinding(Base):
    __tablename__ = "research_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("research_submissions.id", ondelete="CASCADE"), index=True)
    domain_id: Mapped[int | None] = mapped_column(ForeignKey("security_domains.id"))
    career_level_id: Mapped[int | None] = mapped_column(ForeignKey("career_levels.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("competency_categories.id"))
    competency_id: Mapped[int | None] = mapped_column(ForeignKey("competencies.id"))
    candidate_name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str | None] = mapped_column(String(200))
    finding_type: Mapped[str] = mapped_column(String(60))
    technical_knowledge: Mapped[str] = mapped_column(Text, default="")
    practical_capability: Mapped[str] = mapped_column(Text, default="")
    responsibilities: Mapped[str] = mapped_column(Text, default="")
    proficiency_level: Mapped[str] = mapped_column(String(40), default="proficient")
    importance: Mapped[str] = mapped_column(String(40), default="important")
    experience_years_min: Mapped[int | None] = mapped_column(Integer)
    experience_years_max: Mapped[int | None] = mapped_column(Integer)
    evidence_excerpt: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(30), default="normalized")
    details: Mapped[dict | None] = mapped_column(JSON)

    submission: Mapped[ResearchSubmission] = relationship(back_populates="findings")
    domain: Mapped[SecurityDomain | None] = relationship()
    career_level: Mapped[CareerLevel | None] = relationship()
    category: Mapped[CompetencyCategory | None] = relationship()
    competency: Mapped[Competency | None] = relationship()
    domains: Mapped[list["ResearchFindingDomain"]] = relationship(back_populates="finding", cascade="all, delete-orphan")


class ResearchFindingDomain(Base):
    __tablename__ = "research_finding_domains"

    finding_id: Mapped[int] = mapped_column(ForeignKey("research_findings.id", ondelete="CASCADE"), primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("security_domains.id", ondelete="CASCADE"), primary_key=True)

    finding: Mapped[ResearchFinding] = relationship(back_populates="domains")
    domain: Mapped[SecurityDomain] = relationship()


class DraftExpectation(Base):
    __tablename__ = "draft_expectations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("research_submissions.id", ondelete="CASCADE"), index=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("security_domains.id"), index=True)
    career_level_id: Mapped[int] = mapped_column(ForeignKey("career_levels.id"), index=True)
    competency_id: Mapped[int] = mapped_column(ForeignKey("competencies.id"), index=True)
    technical_knowledge: Mapped[str] = mapped_column(Text, default="")
    practical_capability: Mapped[str] = mapped_column(Text, default="")
    qualifications: Mapped[str] = mapped_column(Text, default="")
    tools_technologies: Mapped[str] = mapped_column(Text, default="")
    expectation_description: Mapped[str] = mapped_column(Text)
    proficiency_level: Mapped[str] = mapped_column(String(40))
    importance: Mapped[str] = mapped_column(String(40))
    responsibility_type: Mapped[str] = mapped_column(String(80))
    experience_years_min: Mapped[int | None] = mapped_column(Integer)
    experience_years_max: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(String(120))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_expectation_id: Mapped[int | None] = mapped_column(ForeignKey("domain_level_expectations.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    submission: Mapped[ResearchSubmission] = relationship(back_populates="drafts")
    domain: Mapped[SecurityDomain] = relationship()
    career_level: Mapped[CareerLevel] = relationship()
    competency: Mapped[Competency] = relationship()
    evidence: Mapped[list["DraftEvidence"]] = relationship(back_populates="draft", cascade="all, delete-orphan")
    published_expectation: Mapped[DomainLevelExpectation | None] = relationship(foreign_keys=[published_expectation_id])




class PublicationBatch(Base):
    __tablename__ = "publication_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int | None] = mapped_column(ForeignKey("research_submissions.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

    submission: Mapped[ResearchSubmission | None] = relationship(back_populates="publication_batches")
    changes: Mapped[list["ReviewChange"]] = relationship(back_populates="publication_batch")


class ReviewChange(Base):
    __tablename__ = "review_changes"
    __table_args__ = (UniqueConstraint("finding_id", name="uq_review_change_finding"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("research_submissions.id", ondelete="CASCADE"), index=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("research_findings.id", ondelete="CASCADE"), index=True)
    draft_id: Mapped[int | None] = mapped_column(ForeignKey("draft_expectations.id", ondelete="SET NULL"), index=True)
    target_competency_id: Mapped[int | None] = mapped_column(ForeignKey("competencies.id"), index=True)
    target_expectation_id: Mapped[int | None] = mapped_column(ForeignKey("domain_level_expectations.id"), index=True)
    merge_target_competency_id: Mapped[int | None] = mapped_column(ForeignKey("competencies.id"), index=True)
    publication_batch_id: Mapped[int | None] = mapped_column(ForeignKey("publication_batches.id", ondelete="SET NULL"), index=True)
    change_type: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    original_snapshot: Mapped[dict] = mapped_column(JSON)
    proposed_snapshot: Mapped[dict] = mapped_column(JSON)
    reviewer_snapshot: Mapped[dict | None] = mapped_column(JSON)
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(String(120))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    submission: Mapped[ResearchSubmission] = relationship(back_populates="review_changes")
    finding: Mapped[ResearchFinding] = relationship()
    draft: Mapped[DraftExpectation | None] = relationship()
    target_competency: Mapped[Competency | None] = relationship(foreign_keys=[target_competency_id])
    target_expectation: Mapped[DomainLevelExpectation | None] = relationship(foreign_keys=[target_expectation_id])
    merge_target_competency: Mapped[Competency | None] = relationship(foreign_keys=[merge_target_competency_id])
    publication_batch: Mapped[PublicationBatch | None] = relationship(back_populates="changes")
    audits: Mapped[list["ReviewAudit"]] = relationship(back_populates="change", cascade="all, delete-orphan")


class ReviewAudit(Base):
    __tablename__ = "review_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("review_changes.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(30))
    actor: Mapped[str] = mapped_column(String(120))
    before_snapshot: Mapped[dict | None] = mapped_column(JSON)
    after_snapshot: Mapped[dict | None] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    change: Mapped[ReviewChange] = relationship(back_populates="audits")


class ExpectationRevision(Base):
    __tablename__ = "expectation_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    expectation_id: Mapped[int] = mapped_column(ForeignKey("domain_level_expectations.id", ondelete="CASCADE"), index=True)
    change_id: Mapped[int | None] = mapped_column(ForeignKey("review_changes.id", ondelete="SET NULL"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    expectation: Mapped[DomainLevelExpectation] = relationship()
    change: Mapped[ReviewChange | None] = relationship()

class DraftEvidence(Base):
    __tablename__ = "draft_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("draft_expectations.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("research_sources.id", ondelete="CASCADE"), index=True)
    supporting_excerpt: Mapped[str] = mapped_column(Text)

    draft: Mapped[DraftExpectation] = relationship(back_populates="evidence")
    source: Mapped[ResearchSource] = relationship()

