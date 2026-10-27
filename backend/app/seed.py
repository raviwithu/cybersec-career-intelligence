from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AnalysisVersion,
    CareerLevel,
    Competency,
    CompetencyCategory,
    DomainLevelExpectation,
    SecurityDomain,
)

ILLUSTRATIVE_PREFIX = "Illustrative development seed; not verified market research. "

DOMAIN_SEED = [
    ("web-application-security", "Web Application Security", "Application-layer security engineering and testing.", None, 1),
    ("cloud-api-security", "Cloud API Security", "Security of APIs exposed through cloud platforms and services.", None, 2),
    ("cloud-infrastructure-security", "Cloud Infrastructure Security", "Security architecture and operations for cloud infrastructure.", None, 3),
    ("traditional-server-infrastructure-security", "Traditional Server Infrastructure Security", "Security of conventional server, operating system, and network infrastructure.", None, 4),
    ("embedded-systems-security", "Embedded Systems Security", "Security of embedded devices, firmware, hardware, and connected systems.", None, 5),
]

EMBEDDED_SUBDOMAINS = [
    ("embedded-application-security", "Embedded Application Security", "Security of software applications running on embedded devices.", 1),
    ("operating-system-security", "Operating System Security", "Hardening and protecting embedded operating systems.", 2),
    ("boot-security", "Boot Security", "Secure startup, trust chains, firmware verification, and anti-rollback controls.", 3),
    ("hardware-security", "Hardware Security", "Hardware roots of trust, physical protections, and secure hardware design.", 4),
    ("wireless-security", "Wireless Security", "Security of wireless protocols, radios, and device communications.", 5),
]

CAREER_LEVEL_SEED = [
    ("junior", "Junior", "shared", "Builds foundational capability with defined guidance.", 1),
    ("intermediate", "Intermediate", "shared", "Delivers independent work within an established security practice.", 2),
    ("senior", "Senior", "shared", "Leads complex work, makes technical decisions, and mentors others.", 3),
    ("manager", "Manager", "management", "Leads people, planning, prioritization, and operational outcomes.", 4),
    ("architect", "Architect", "technical", "Defines technical direction, boundaries, and cross-system security design.", 5),
    ("director", "Director", "management", "Owns organizational security outcomes, strategy, and risk decisions.", 6),
]

CATEGORY_SEED = [
    ("technical-knowledge", "Technical Knowledge"),
    ("technical-skills", "Technical Skills"),
    ("tools-technologies", "Tools and Technologies"),
    ("security-architecture", "Security Architecture"),
    ("security-testing", "Security Testing"),
    ("experience", "Experience"),
    ("education", "Education"),
    ("certifications", "Certifications"),
    ("security-standards", "Security Standards"),
    ("responsibilities", "Responsibilities"),
    ("leadership", "Leadership"),
    ("communication", "Communication"),
    ("risk-management", "Risk Management"),
]

COMPETENCY_SEED = [
    ("secure-boot", "Secure Boot", "security-architecture", "Design and evaluate verified device startup."),
    ("chain-of-trust", "Chain of Trust", "security-architecture", "Establish and maintain verifiable trust from hardware through software."),
    ("hardware-root-of-trust", "Hardware Root of Trust", "technical-knowledge", "Use hardware-backed primitives to protect device trust anchors."),
    ("embedded-linux-security", "Embedded Linux Security", "technical-knowledge", "Apply hardening and runtime protection to embedded Linux systems."),
    ("firmware-analysis", "Firmware Analysis", "security-testing", "Analyze firmware for vulnerabilities, unsafe defaults, and tampering indicators."),
    ("api-authorization", "API Authorization", "technical-skills", "Design and test authorization boundaries for service APIs."),
    ("kubernetes-security", "Kubernetes Security", "tools-technologies", "Secure Kubernetes control planes, workloads, and deployment paths."),
    ("container-security", "Container Security", "tools-technologies", "Protect container images, runtimes, and supply chains."),
    ("threat-modeling", "Threat Modeling", "security-architecture", "Identify assets, trust boundaries, threats, and mitigations."),
    ("penetration-testing", "Penetration Testing", "security-testing", "Plan and perform authorized security testing with actionable findings."),
    ("cryptographic-key-management", "Cryptographic Key Management", "technical-knowledge", "Govern key generation, storage, rotation, use, and destruction."),
]

EXPECTATION_SEED = [
    (
        "boot-security",
        "architect",
        "secure-boot",
        "Design secure boot architecture, define trust boundaries, establish key provisioning requirements, and evaluate resistance to firmware tampering.",
        "expert",
        "essential",
        "design",
        7,
        None,
    ),
    (
        "cloud-api-security",
        "senior",
        "api-authorization",
        "Define authorization patterns, review privilege boundaries, and lead testing of API access-control decisions.",
        "advanced",
        "essential",
        "leadership",
        4,
        8,
    ),
    (
        "web-application-security",
        "intermediate",
        "threat-modeling",
        "Apply threat modeling to application changes and document prioritized mitigations with engineering teams.",
        "proficient",
        "important",
        "execution",
        2,
        5,
    ),
]


def _domain(db: Session, slug: str) -> SecurityDomain:
    return db.scalar(select(SecurityDomain).where(SecurityDomain.slug == slug))


def seed_reference_data(db: Session) -> None:
    domains = {}
    for slug, name, description, parent_id, display_order in DOMAIN_SEED:
        domain = _domain(db, slug)
        if domain is None:
            domain = SecurityDomain(slug=slug, name=name, description=description, parent_id=parent_id, display_order=display_order)
            db.add(domain)
            db.flush()
        domains[slug] = domain

    embedded_parent = domains["embedded-systems-security"]
    for slug, name, description, display_order in EMBEDDED_SUBDOMAINS:
        child = _domain(db, slug)
        if child is None:
            db.add(SecurityDomain(slug=slug, name=name, description=description, parent_id=embedded_parent.id, display_order=display_order))

    for slug, name, track, description, display_order in CAREER_LEVEL_SEED:
        if db.scalar(select(CareerLevel).where(CareerLevel.slug == slug)) is None:
            db.add(CareerLevel(slug=slug, name=name, career_track=track, description=description, display_order=display_order))

    categories = {}
    for slug, name in CATEGORY_SEED:
        category = db.scalar(select(CompetencyCategory).where(CompetencyCategory.slug == slug))
        if category is None:
            category = CompetencyCategory(slug=slug, name=name, description=f"{name} competency classification.")
            db.add(category)
            db.flush()
        categories[slug] = category

    competencies = {}
    for slug, name, category_slug, description in COMPETENCY_SEED:
        competency = db.scalar(select(Competency).where(Competency.slug == slug))
        if competency is None:
            competency = Competency(
                slug=slug,
                name=name,
                description=ILLUSTRATIVE_PREFIX + description,
                category_id=categories[category_slug].id,
            )
            db.add(competency)
            db.flush()
        competencies[slug] = competency

    for domain_slug, level_slug, competency_slug, description, proficiency, importance, responsibility, years_min, years_max in EXPECTATION_SEED:
        domain = domains.get(domain_slug) or _domain(db, domain_slug)
        level = db.scalar(select(CareerLevel).where(CareerLevel.slug == level_slug))
        competency = competencies.get(competency_slug) or db.scalar(select(Competency).where(Competency.slug == competency_slug))
        exists = db.scalar(
            select(DomainLevelExpectation).where(
                DomainLevelExpectation.domain_id == domain.id,
                DomainLevelExpectation.career_level_id == level.id,
                DomainLevelExpectation.competency_id == competency.id,
                DomainLevelExpectation.expectation_description == ILLUSTRATIVE_PREFIX + description,
            )
        )
        if exists is None:
            db.add(
                DomainLevelExpectation(
                    domain_id=domain.id,
                    career_level_id=level.id,
                    competency_id=competency.id,
                    expectation_description=ILLUSTRATIVE_PREFIX + description,
                    proficiency_level=proficiency,
                    importance=importance,
                    responsibility_type=responsibility,
                    experience_years_min=years_min,
                    experience_years_max=years_max,
                )
            )

    if db.scalar(select(AnalysisVersion).where(AnalysisVersion.version == "illustrative-v1")) is None:
        db.add(
            AnalysisVersion(
                version="illustrative-v1",
                analysis_date=datetime.now(timezone.utc),
                description="Illustrative development seed for Phase 2 schema and API testing.",
                methodology="Hand-authored examples only; not verified market research.",
            )
        )
    db.commit()
