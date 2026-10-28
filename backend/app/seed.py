from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AnalysisVersion,
    CareerLevel,
    Competency,
    CompetencyCategory,
    DomainLevelExpectation,
    Industry,
    IndustryAlias,
    SecurityDomain,
    SecurityDomainAlias,
    CareerLevelAlias,
    CompetencyCategoryAlias,
    KnowledgeTopic,
    KnowledgeTopicCompetency,
    KnowledgeTopicDomain,
    KnowledgeTopicLevel,
)

ILLUSTRATIVE_PREFIX = "Illustrative development seed; not verified market research. "

INDUSTRY_SEED = [
    ("automotive", "Automotive", "Vehicle platforms, connected mobility, and automotive product security.", 1, [("Connected Vehicles", False, None), ("Mobility", True, "Use Automotive when the source explicitly addresses vehicle or mobility systems.")]),
    ("medical-devices-healthcare-technology", "Medical Devices and Healthcare Technology", "Medical devices, clinical technology, and healthcare platforms.", 2, [("Medical Devices", False, None), ("MedTech", False, None)]),
    ("financial-services", "Financial Services", "Banking, payments, insurance, and financial technology.", 3, [("Banking", False, None), ("FinTech", False, None)]),
    ("aerospace-defense", "Aerospace and Defense", "Aerospace systems, defense platforms, and mission-critical security.", 4, []),
    ("industrial-automation-ot", "Industrial Automation and Operational Technology", "Industrial control, automation, ICS, and operational technology environments.", 5, [("Industrial Automation", False, None), ("OT", True, "Use this alias when the source explicitly concerns operational technology."), ("ICS", True, "Use this alias when the source explicitly concerns industrial control systems.")]),
    ("consumer-electronics", "Consumer Electronics", "Consumer devices, home technology, and device ecosystems.", 6, []),
    ("telecommunications", "Telecommunications", "Telecom networks, carrier infrastructure, and communications services.", 7, []),
    ("enterprise-software-saas", "Enterprise Software and SaaS", "Enterprise applications, software products, and SaaS platforms.", 8, []),
    ("cloud-infrastructure-services", "Cloud Infrastructure and Services", "Cloud platforms, hosted infrastructure, and managed services.", 9, []),
    ("energy-utilities", "Energy and Utilities", "Energy generation, distribution, utilities, and grid technology.", 10, []),
    ("government-public-sector", "Government and Public Sector", "Government services, public infrastructure, and civic technology.", 11, []),
    ("general-cross-industry", "General / Cross-Industry", "Evidence-backed expectations applicable across industries.", 12, [("General", False, None), ("Cross-Industry", False, None)]),
]


DOMAIN_SEED = [
    ("web-application-security", "Web Application Security", "Application-layer security engineering and testing.", None, 1),
    ("cloud-api-security", "Cloud API Security", "Security of APIs exposed through cloud platforms and services.", None, 2),
    ("cloud-infrastructure-security", "Cloud Infrastructure Security", "Security architecture and operations for cloud infrastructure.", None, 3),
    ("traditional-server-infrastructure-security", "Traditional Server Infrastructure Security", "Security of conventional server, operating system, and network infrastructure.", None, 4),
    ("embedded-systems-security", "Embedded Systems Security", "Security of embedded devices, firmware, hardware, and connected systems.", None, 5),
    ("governance-risk-compliance", "Governance, Risk, and Compliance", "Security governance, risk assessment and management, third-party and transaction risk, policy, audit, and regulatory or framework compliance such as NIST, ISO 27001, and CMMC.", None, 6),
    ("identity-access-management", "Identity and Access Management", "Identity lifecycle, authentication, authorization, privileged access, and directory or identity-provider security.", None, 7),
    ("security-operations", "Security Operations", "Threat detection, monitoring, incident response, vulnerability management, and security tooling operations.", None, 8),
    ("ai-system-security", "AI System Security", "Security of AI and machine-learning systems themselves: LLM and generative-AI application security (prompt injection, insecure output handling, agent and tool-use abuse), model and training-data integrity (data poisoning, model theft, model supply chain and provenance), adversarial machine learning, AI red teaming, and secure MLOps. References include the OWASP Top 10 for LLM Applications, MITRE ATLAS, NIST AI RMF, and ISO/IEC 42001. Use when the asset being protected is an AI or ML system.", None, 9),
    ("ai-enabled-security-products", "AI-Enabled Security Products", "Building and operating security products that use AI or machine learning as a core capability: ML-based threat detection and anomaly detection, AI-assisted SOC triage and investigation, LLM-powered security copilots and automation, malware and phishing classification models, and the data pipelines, model evaluation, false-positive tuning, and drift monitoring behind them. Use when AI is the tool used to deliver security outcomes rather than the asset being protected.", None, 10),
    ("security-automation", "Security Automation", "Automating security workflows and controls through SOAR, workflow orchestration, security-as-code, policy-as-code, automated vulnerability management, control validation, and repeatable detection or response actions. Use when workflow automation is the primary security capability, rather than AI being the protected asset or the enabling technology.", None, 11),
]

DOMAIN_ALIAS_SEED = [
    ("security-operations", "SecOps", False, None),
    ("governance-risk-compliance", "GRC", False, None),
]

CAREER_LEVEL_ALIAS_SEED = [
    ("junior", "Entry", False, None),
    ("intermediate", "Mid-level", False, None),
    ("senior", "Lead", False, None),
    ("architect", "Staff", False, None),
    ("architect", "Principal", False, None),
    ("director", "Head", False, None),
]

CATEGORY_ALIAS_SEED = [
    ("security-standards", "Standards and Regulations", False, None),
    ("education", "Qualifications", False, None),
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

def seed_industries(db: Session) -> dict[str, Industry]:
    industries: dict[str, Industry] = {}
    for slug, name, description, display_order, aliases in INDUSTRY_SEED:
        industry = db.scalar(select(Industry).where(Industry.slug == slug))
        if industry is None:
            industry = Industry(slug=slug, name=name, description=description, display_order=display_order, is_active=True)
            db.add(industry)
            db.flush()
        industries[slug] = industry
        for alias, requires_context, context_hint in aliases:
            normalized = alias.casefold().strip()
            if db.scalar(select(IndustryAlias).where(IndustryAlias.normalized_alias == normalized)) is None:
                db.add(IndustryAlias(industry_id=industry.id, alias=alias, normalized_alias=normalized, requires_context=requires_context, context_hint=context_hint))
    return industries


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
    seed_industries(db)
    domains = {}
    for slug, name, description, parent_id, display_order in DOMAIN_SEED:
        domain = _domain(db, slug)
        if domain is None:
            domain = SecurityDomain(slug=slug, name=name, description=description, parent_id=parent_id, display_order=display_order)
            db.add(domain)
            db.flush()
        domains[slug] = domain

    for domain_slug, alias, requires_context, context_hint in DOMAIN_ALIAS_SEED:
        domain = domains[domain_slug]
        normalized = alias.casefold().strip()
        if db.scalar(select(SecurityDomainAlias).where(SecurityDomainAlias.normalized_alias == normalized)) is None:
            db.add(SecurityDomainAlias(domain_id=domain.id, alias=alias, normalized_alias=normalized, requires_context=requires_context, context_hint=context_hint))

    embedded_parent = domains["embedded-systems-security"]
    for slug, name, description, display_order in EMBEDDED_SUBDOMAINS:
        child = _domain(db, slug)
        if child is None:
            db.add(SecurityDomain(slug=slug, name=name, description=description, parent_id=embedded_parent.id, display_order=display_order))

    for slug, name, track, description, display_order in CAREER_LEVEL_SEED:
        if db.scalar(select(CareerLevel).where(CareerLevel.slug == slug)) is None:
            db.add(CareerLevel(slug=slug, name=name, career_track=track, description=description, display_order=display_order))
    db.flush()

    levels = {item.slug: item for item in db.scalars(select(CareerLevel)).all()}
    for level_slug, alias, requires_context, context_hint in CAREER_LEVEL_ALIAS_SEED:
        level = levels[level_slug]
        normalized = alias.casefold().strip()
        if db.scalar(select(CareerLevelAlias).where(CareerLevelAlias.normalized_alias == normalized)) is None:
            db.add(CareerLevelAlias(career_level_id=level.id, alias=alias, normalized_alias=normalized, requires_context=requires_context, context_hint=context_hint))

    categories = {}
    for slug, name in CATEGORY_SEED:
        category = db.scalar(select(CompetencyCategory).where(CompetencyCategory.slug == slug))
        if category is None:
            category = CompetencyCategory(slug=slug, name=name, description=f"{name} competency classification.")
            db.add(category)
            db.flush()
        categories[slug] = category

    for category_slug, alias, requires_context, context_hint in CATEGORY_ALIAS_SEED:
        category = categories[category_slug]
        normalized = alias.casefold().strip()
        if db.scalar(select(CompetencyCategoryAlias).where(CompetencyCategoryAlias.normalized_alias == normalized)) is None:
            db.add(CompetencyCategoryAlias(category_id=category.id, alias=alias, normalized_alias=normalized, requires_context=requires_context, context_hint=context_hint))

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


    db.flush()
    # Keep the public checklist populated from the existing canonical competency seed.
    for competency in db.scalars(select(Competency)).all():
        topic = db.scalar(select(KnowledgeTopic).where(KnowledgeTopic.slug == competency.slug))
        expectations = list(db.scalars(
            select(DomainLevelExpectation)
            .where(DomainLevelExpectation.competency_id == competency.id)
            .order_by(DomainLevelExpectation.id)
        ).all())
        if topic is None:
            topic = KnowledgeTopic(
                name=competency.name,
                slug=competency.slug,
                description=competency.description,
                category_id=competency.category_id,
                aliases=[],
                publication_status="published",
                is_active=True,
                version=1,
                published_at=datetime.now(timezone.utc),
            )
            db.add(topic)
            db.flush()
            db.add(KnowledgeTopicCompetency(topic_id=topic.id, competency_id=competency.id))
        if not topic.domains:
            for domain_id in sorted({item.domain_id for item in expectations}):
                db.add(KnowledgeTopicDomain(topic_id=topic.id, domain_id=domain_id))
        if not topic.level_expectations:
            # Several domain expectations can share a level/industry; the topic keeps one per pair.
            seen_levels = set()
            for item in expectations:
                key = (item.career_level_id, item.industry_id)
                if key in seen_levels:
                    continue
                seen_levels.add(key)
                db.add(KnowledgeTopicLevel(
                    topic_id=topic.id,
                    career_level_id=item.career_level_id,
                    industry_id=item.industry_id,
                    expectation=item.expectation_description,
                    practical_capability=item.practical_capability,
                ))

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
