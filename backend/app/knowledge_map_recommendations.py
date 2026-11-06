from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
from copy import deepcopy
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .knowledge_contract_schemas import KnowledgeProposalCreate, KnowledgeProposalReview, KnowledgeSourceReference, _clean_text
from .knowledge_contract_service import CVE_PATTERN, _source_values, create_proposal, get_proposal, review_proposal
from .knowledge_map_proposals import find_duplicate_topic
from .models import KnowledgeProposalSource, KnowledgeTopic, KnowledgeTopicDomain, KnowledgeTopicProposal, SecurityDomain
from .ollama_client import OllamaError
from .phase5_api import providers
from .provider_common import ProviderError
from .videorag_client import VideoRagClient

# Admin-triggered recommendations for the Foundations, Security and Common Vulnerabilities of any topic directly under a
# domain, whether its branches are filled or empty. The administrator picks the RAG knowledge DB, Kimi, or both together.
# Recommendations are returned, never stored; only the ones the administrator selects become proposals, and those stop
# at review. Nothing here approves or publishes.
#
# "both" drafts from RAG where it has an answer, has Kimi check each draft, then lets Kimi cover what RAG could not.
# RAG comes from private course material and Kimi is remote, so Kimi gets the short draft text only: never transcripts,
# screen text or source names. Only this option sends it. Kimi's check is a model's opinion, so references stay unverified.

BRANCHES = {"foundations": "Foundations", "security": "Security", "vulnerabilities": "Common Vulnerabilities"}
RAG_LIST_FORMAT = "'Name: one sentence description'"
RAG_VULNERABILITY_LIST_FORMAT = "'Name: one sentence description. Example: one concrete example of how it shows up.'"
RAG_BRANCH_ASK = {"foundations": "the core concepts someone must understand first", "security": "the main security controls and defensive practices", "vulnerabilities": "the common vulnerabilities and classes of weakness"}
OPEN_STATUSES = ("draft", "review", "deferred", "approved")
# An approved proposal has passed review, so it counts as filled but its text is left alone.
EDITABLE_STATUSES = {"draft", "review", "deferred"}
MAX_ADDITIONS_PER_BRANCH = 2
MAX_ADDITIONS_EMPTY_BRANCH = 4
MAX_RAG_ITEMS = 12
RAG_WORKERS = 2
MAX_DESCRIPTION = 1200
MAX_SOURCES = 3
MAX_NOTE = 300
STOP_WORDS = {"a", "an", "and", "for", "in", "of", "on", "or", "the", "to", "with"}

videorag = VideoRagClient(get_settings())


class RecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain_id: int = Field(ge=1)
    source: Literal["rag", "kimi", "both"]
    # None searches every indexed RAG domain. Most map domains have no RAG domain of their own.
    rag_domain: str | None = Field(default=None, pattern=r"^[a-z0-9-]{1,60}$")


class RecommendationSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    locator: str | None = Field(default=None, max_length=300)
    document_identifier: str | None = Field(default=None, max_length=500)
    content_hash: str | None = Field(default=None, min_length=64, max_length=64)


class RecommendationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["update_description", "add_topic"]
    # What an update applies to: "proposal:<id>" for a pending topic, "topic:<id>" for a published one.
    ref: str | None = Field(default=None, pattern=r"^(proposal|topic):[0-9]{1,12}$")
    # The pending proposal's version when this was recommended, so a later edit is not overwritten.
    expected_version: int | None = Field(default=None, ge=1)
    branch: Literal["foundations", "security", "vulnerabilities"]
    name: str = Field(min_length=1, max_length=120)
    current_description: str | None = Field(default=None, max_length=4000)
    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION)
    aliases: list[str] = Field(default_factory=list, max_length=5)
    weak: bool = False
    sources: list[RecommendationSource] = Field(default_factory=list, max_length=MAX_SOURCES)
    # Set only by "both": what Kimi made of the RAG draft, or kimi_only where RAG had nothing.
    verification: Literal["confirmed", "corrected", "unchecked", "kimi_only"] | None = None
    verification_note: str | None = Field(default=None, max_length=MAX_NOTE)

    @model_validator(mode="after")
    def update_needs_ref(self):
        if self.kind == "update_description" and not self.ref:
            raise ValueError("An update needs a ref")
        return self


class RecommendationSubmission(RecommendationRequest):
    items: list[RecommendationItem] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def both_needs_verification(self):
        if self.source == "both" and any(item.verification is None for item in self.items):
            raise ValueError("Each item needs its verification")
        return self


class _KimiUpdate(BaseModel):
    ref: str
    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION)


class _KimiAddition(BaseModel):
    branch: Literal["foundations", "security", "vulnerabilities"]
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION)
    aliases: list[str] = Field(default_factory=list, max_length=5)


class _KimiCheck(BaseModel):
    id: str
    verdict: Literal["confirmed", "corrected", "rejected"]
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION)
    note: str = ""


def _new_topic_slots(row: KnowledgeTopicProposal) -> list[dict[str, Any]]:
    content = row.proposed_content or {}
    if row.action == "PLACE_TOPIC":
        return [content]
    return [item for item in content.get("placements") or [] if isinstance(item, dict)]


def _branch_items(db: Session) -> dict[tuple[int, int], list[dict[str, Any]]]:
    """Everything in a topic's branches, keyed by (domain_id, parent_topic_id): published placements and open proposals."""
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
    links = db.execute(
        select(KnowledgeTopicDomain, KnowledgeTopic).join(KnowledgeTopic, KnowledgeTopic.id == KnowledgeTopicDomain.topic_id)
        .where(KnowledgeTopicDomain.parent_topic_id.is_not(None), KnowledgeTopicDomain.map_branch.is_not(None), KnowledgeTopic.is_active.is_(True), KnowledgeTopic.publication_status == "published")
    ).all()
    for link, topic in links:
        grouped.setdefault((link.domain_id, link.parent_topic_id), []).append({"ref": f"topic:{topic.id}", "name": topic.name, "description": topic.description or "", "branch": link.map_branch, "editable": True, "version": None})
    rows = db.scalars(select(KnowledgeTopicProposal).where(KnowledgeTopicProposal.action.in_(("CREATE_TOPIC", "PLACE_TOPIC")), KnowledgeTopicProposal.status.in_(OPEN_STATUSES)).order_by(KnowledgeTopicProposal.id)).all()
    placed_topics = {row.topic_id for row in rows if row.topic_id}
    names = {topic.id: topic for topic in db.scalars(select(KnowledgeTopic).where(KnowledgeTopic.id.in_(placed_topics))).all()} if placed_topics else {}
    for row in rows:
        metadata = (row.proposed_content or {}).get("topic")
        creates = row.action == "CREATE_TOPIC" and isinstance(metadata, dict)
        topic = names.get(row.topic_id)
        if not creates and topic is None:
            continue
        for slot in _new_topic_slots(row):
            if slot.get("parent_topic_id") is None or slot.get("map_branch") not in BRANCHES:
                continue
            grouped.setdefault((slot["domain_id"], slot["parent_topic_id"]), []).append({
                "ref": f"proposal:{row.id}",
                "name": metadata.get("name", "") if creates else topic.name,
                "description": metadata.get("description", "") if creates else topic.description or "",
                "branch": slot["map_branch"],
                # A pending placement of an existing topic has no description of its own to change.
                "editable": creates and row.status in EDITABLE_STATUSES,
                "version": row.version,
            })
    return grouped


def _counts(items: list[dict[str, Any]]) -> dict[str, int]:
    return {branch: sum(item["branch"] == branch for item in items) for branch in BRANCHES}


def _rag_domain_for(domain: SecurityDomain, available: list[str]) -> str | None:
    words = set(re.split(r"[^a-z0-9]+", domain.slug.casefold()))
    return next((slug for slug in available if slug in words), None)


def _branch_parents(db: Session) -> list[tuple[KnowledgeTopic, SecurityDomain]]:
    """Every topic that can have branches: published and directly under an active domain. A topic inside a branch has none."""
    return db.execute(
        select(KnowledgeTopic, SecurityDomain).join(KnowledgeTopicDomain, KnowledgeTopicDomain.topic_id == KnowledgeTopic.id).join(SecurityDomain, SecurityDomain.id == KnowledgeTopicDomain.domain_id)
        .where(KnowledgeTopicDomain.parent_topic_id.is_(None), KnowledgeTopicDomain.map_branch.is_not(None), KnowledgeTopic.is_active.is_(True), KnowledgeTopic.publication_status == "published", SecurityDomain.is_active.is_(True))
    ).all()


def _source_status() -> tuple[dict[str, Any], dict[str, Any]]:
    settings = get_settings()
    rag: dict[str, Any] = {"id": "rag", "label": "RAG knowledge DB", "status": "unconfigured", "detail": "Set VIDEORAG_BASE_URL and VIDEORAG_ACCESS_KEY.", "domains": []}
    if videorag.configured:
        try:
            coverage = videorag.coverage()
            rag["domains"] = [{"slug": item["slug"], "name": item.get("name") or item["slug"], "indexed": item.get("indexed", 0), "indexed_pct": item.get("indexed_pct", 0)} for item in coverage if item.get("slug") and item.get("indexed")]
            rag.update(status="connected", detail="Private course material. Answers show their sources.")
        except ProviderError as exc:
            rag.update(status="unavailable", detail=exc.message)
    kimi: dict[str, Any] = {"id": "kimi", "label": "Kimi", "model": settings.kimi_model, "status": "unconfigured", "detail": "Set OPENWEBUI_BASE_URL."}
    if providers.openwebui.configured:
        try:
            found = any(model.model_id == settings.kimi_model for model in providers.openwebui.list_model_records())
            kimi.update(status="connected" if found else "unavailable", detail=f"{settings.kimi_model} through OpenWebUI. Not checked against a source." if found else f"Model {settings.kimi_model} is not available in OpenWebUI.")
        except ProviderError as exc:
            kimi.update(status="unavailable", detail=exc.message)
    return rag, kimi


def _both_status(rag: dict[str, Any], kimi: dict[str, Any]) -> dict[str, Any]:
    both: dict[str, Any] = {"id": "both", "label": "RAG + Kimi", "status": kimi["status"], "detail": "Needs Kimi, which checks the RAG drafts."}
    if kimi["status"] == "connected":
        both["detail"] = "RAG drafts first, Kimi checks each draft and covers what RAG could not. Kimi sees the draft text, not transcripts or source names." if rag["status"] == "connected" else "RAG is not available, so this would use Kimi alone."
    return both


def recommendation_options(db: Session) -> dict[str, Any]:
    rag, kimi = _source_status()
    available = [item["slug"] for item in rag["domains"]]
    grouped = _branch_items(db)
    topics = [{
        "topic_id": topic.id, "topic_name": topic.name, "domain_id": domain.id, "domain_name": domain.name,
        "counts": _counts(grouped.get((domain.id, topic.id), [])), "rag_domain": _rag_domain_for(domain, available),
    } for topic, domain in _branch_parents(db)]
    return {"sources": [rag, kimi, _both_status(rag, kimi)], "topics": sorted(topics, key=lambda item: (item["domain_name"].casefold(), item["topic_name"].casefold()))}


def _branch_topic(db: Session, topic_id: int, domain_id: int) -> tuple[KnowledgeTopic, SecurityDomain, list[dict[str, Any]], dict[tuple[int, int], list[dict[str, Any]]]]:
    topic = db.get(KnowledgeTopic, topic_id)
    domain = db.get(SecurityDomain, domain_id)
    if topic is None or not topic.is_active or domain is None:
        raise HTTPException(status_code=404, detail="Knowledge topic or domain was not found")
    link = db.get(KnowledgeTopicDomain, (topic_id, domain_id))
    if topic.publication_status != "published" or link is None or link.map_branch is None or link.parent_topic_id is not None:
        raise HTTPException(status_code=409, detail="Only a published topic directly under this domain has branches")
    grouped = _branch_items(db)
    return topic, domain, grouped.get((domain_id, topic_id), []), grouped


def _tokens(name: str) -> set[str]:
    return {word for word in re.split(r"[^a-z0-9]+", name.casefold()) if word and word not in STOP_WORDS}


def _overlaps(first: str, second: str) -> bool:
    a, b = _tokens(first), _tokens(second)
    return bool(a and b) and len(a & b) / min(len(a), len(b)) >= 0.6


def _text_problem(text: str) -> str | None:
    if CVE_PATTERN.search(text):
        return "it names a CVE, which needs a verified source"
    try:
        _clean_text(text)
    except ValueError:
        return "it contains executable HTML"
    return None


class _Additions:
    """Keeps new topics distinct from everything in the domain, including other parents' items, since a topic has one place per domain."""

    def __init__(self, db: Session, domain_names: list[str], pending_names: set[str], items: list[dict[str, Any]]):
        self.db, self.names, self.pending, self.per_branch = db, list(domain_names), pending_names, dict.fromkeys(BRANCHES, 0)
        self.limits = {branch: MAX_ADDITIONS_PER_BRANCH if count else MAX_ADDITIONS_EMPTY_BRANCH for branch, count in _counts(items).items()}

    def room(self) -> dict[str, int]:
        return {branch: self.limits[branch] - used for branch, used in self.per_branch.items()}

    def full(self, branch: str) -> bool:
        return self.per_branch[branch] >= self.limits[branch]

    def reason_to_drop(self, branch: str, name: str, description: str) -> str | None:
        if self.full(branch):
            return f"the limit of {self.limits[branch]} new topics for this branch was reached"
        clash = next((other for other in self.names if _overlaps(name, other)), None)
        if clash:
            return f"it overlaps {clash}"
        if name.casefold() in self.pending or find_duplicate_topic(self.db, [name]) is not None:
            return "a topic with this name already exists"
        return _text_problem(f"{name} {description}")

    def accept(self, branch: str, name: str) -> None:
        self.names.append(name)
        self.per_branch[branch] += 1

    def release(self, branch: str) -> None:
        """Frees the slot of a rejected topic. Its name stays listed, so it cannot come back."""
        self.per_branch[branch] -= 1


def _update(item: dict[str, Any], description: str, *, weak: bool = False, sources: list[dict[str, Any]] | None = None, verification: str | None = None) -> dict[str, Any]:
    return {"kind": "update_description", "ref": item["ref"], "expected_version": item["version"], "branch": item["branch"], "name": item["name"], "current_description": item["description"], "description": description, "aliases": [], "weak": weak, "sources": sources or [], "verification": verification, "verification_note": None}


def _addition(branch: str, name: str, description: str, *, aliases: list[str] | None = None, weak: bool = False, sources: list[dict[str, Any]] | None = None, verification: str | None = None) -> dict[str, Any]:
    return {"kind": "add_topic", "ref": None, "expected_version": None, "branch": branch, "name": name, "current_description": None, "description": description, "aliases": aliases or [], "weak": weak, "sources": sources or [], "verification": verification, "verification_note": None}


KIMI_SYSTEM = "You are a senior security engineer editing a security knowledge base for defenders and reviewers. Be technically exact. Reply with one JSON object only, no markdown."


def _kimi_prompt(topic: KnowledgeTopic, domain: SecurityDomain, items: list[dict[str, Any]], covered: list[str], room: dict[str, int], drafts: list[dict[str, str]] | None = None) -> str:
    listing = {label: [{"ref": item["ref"], "name": item["name"], "description": item["description"]} for item in items if item["branch"] == branch and item["editable"]] for branch, label in BRANCHES.items()}
    fixed = [item["name"] for item in items if not item["editable"]]
    about = f"\nAbout it: {topic.description}" if topic.description else ""
    review = f"""
Drafts to verify, each written from other material:
{json.dumps(drafts, indent=1)}
""" if drafts else ""
    check = f"""0. For every draft, return a check. Use "confirmed" if it is technically accurate and follows the description rules below, "corrected" with a fixed description if it is partly wrong or incomplete, or "rejected" if it is wrong, does not belong under {topic.name}, or its name is a heading or summary rather than one specific topic. Add a note of at most 200 characters saying why. Keep the id exactly. Do not repeat drafts as updates or additions.
""" if drafts else ""
    shape = '"checks":[{"id":"...","verdict":"confirmed|corrected|rejected","description":"only when corrected","note":"..."}],' if drafts else ""
    return f"""Parent topic: {topic.name} (domain: {domain.name}).{about}
Each parent topic has three branches of child topics:
- Foundations: what someone must understand first.
- Security: controls and defensive practices.
- Common Vulnerabilities: classes of weakness.
{review}
Child topics you may revise:
{json.dumps(listing, indent=1)}

Already covered, do not suggest these or anything overlapping them:
{json.dumps(sorted({*fixed, *covered}), indent=1)}

Description rules: 2-3 plain sentences, at most 320 characters, saying what it is and why it matters under {topic.name}. A Common Vulnerabilities description must then end with one concrete example of how the weakness shows up in real systems, starting "Example:", described at design level, at most 420 characters in total.

Tasks:
{check}1. For every child topic you may revise, write an improved description. Keep the ref exactly. Do not rename items.
2. Suggest missing child topics, at most this many per branch: {json.dumps(room)}. Every branch must end up with child topics, so a branch with none listed must get at least 2. Suggest none for a branch that is already complete.

Rules: no CVE numbers, no product or vendor incident claims, no statistics, no exploit steps or payloads. Describe weakness classes and defences only. If you are unsure of a fact, leave it out.

Return exactly:
{{{shape}"updates":[{{"ref":"...","description":"..."}}],"additions":[{{"branch":"foundations|security|vulnerabilities","name":"Title Case Name","description":"...","aliases":[]}}]}}"""


def _parse_kimi(raw: str) -> dict[str, Any]:
    text = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.S).strip()
    try:
        value = json.loads(text[text.index("{"):text.rindex("}") + 1])
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Kimi did not return valid JSON; nothing was stored") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=502, detail="Kimi did not return a JSON object; nothing was stored")
    return value


def _ask_kimi(prompt: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        raw = providers.complete_selected("openwebui", settings.kimi_model, KIMI_SYSTEM, prompt, settings.recommendation_timeout_seconds)
    except Exception as exc:
        reason = str(exc) if isinstance(exc, (ProviderError, OllamaError)) else type(exc).__name__
        raise HTTPException(status_code=503, detail=f"Kimi could not produce recommendations: {reason}") from exc
    return _parse_kimi(raw)


def _kimi_items(reply: dict[str, Any], items: list[dict[str, Any]], additions: _Additions, verification: str | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    editable = {item["ref"]: item for item in items if item["editable"]}
    recommendations, warnings = [], []
    for value in reply.get("updates") or []:
        try:
            update = _KimiUpdate.model_validate(value)
        except ValidationError:
            warnings.append("An update was dropped: it does not match the expected shape.")
            continue
        item = editable.get(update.ref)
        problem = "it names an item that cannot be revised" if item is None else _text_problem(update.description)
        if problem:
            warnings.append(f"An update was dropped: {problem}.")
        elif update.description.strip() != item["description"].strip():
            recommendations.append(_update(item, update.description.strip(), verification=verification))
    for value in reply.get("additions") or []:
        try:
            addition = _KimiAddition.model_validate(value)
        except ValidationError:
            warnings.append("A new topic was dropped: it does not match the expected shape.")
            continue
        problem = additions.reason_to_drop(addition.branch, addition.name, addition.description)
        if problem:
            warnings.append(f"{addition.name} was dropped: {problem}.")
            continue
        additions.accept(addition.branch, addition.name)
        recommendations.append(_addition(addition.branch, addition.name.strip(), addition.description.strip(), aliases=addition.aliases, verification=verification))
    return recommendations, warnings


def _plain(text: str) -> str:
    text = re.sub(r"\s*\[\d+\]", "", text or "")
    text = re.sub(r"^#+\s*", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text.replace("*", "").replace("`", "")).strip()


def _first_sentences(text: str, count: int = 3) -> str:
    short = " ".join(re.split(r"(?<=[.!?])\s+", text)[:count])[:MAX_DESCRIPTION]
    return short[:1].upper() + short[1:]


# Answers list items as "Name: description" lines, with or without a bullet or bold.
LIST_LINE = re.compile(r"^\s*(?:(?:[-*•]|\d+[.)])\s+)?\*{0,2}(?P<name>[A-Z][^*:–—\n]{2,79}?)\*{0,2}\s*(?:[:–—]|\s-\s)\*{0,2}\s*(?P<text>\S.*)$", re.M)
MAX_NAME_WORDS = 7
# The service can mark these grounded, so a refusal has to be recognised from its reasons and wording.
REFUSAL = re.compile(r"\bsources?\b.{0,40}\b(?:do not|does not|don't|doesn't|cannot)\b|\bcannot (?:give|provide|answer)\b|\bno information\b", re.I)


def _listed(answer: str) -> list[tuple[str, str]]:
    pairs = [(_plain(match["name"]), _plain(match["text"])) for match in LIST_LINE.finditer(answer or "")]
    return [(name, text) for name, text in pairs if text and len(name.split()) <= MAX_NAME_WORDS]


def _is_refusal(answer: dict[str, Any]) -> bool:
    reasons = " ".join(str(reason) for reason in answer.get("reasons") or [])
    return "don't cover" in reasons.replace("’", "'") or bool(REFUSAL.search(_plain(answer.get("answer", ""))))


def _rag_sources(answer: dict[str, Any]) -> list[dict[str, Any]]:
    """Enough to find the passage again. Transcript and screen text stay in the knowledge DB."""
    picked, seen = [], set()
    for source in answer.get("sources") or []:
        where = source.get("locator") or {}
        seconds = int(where.get("t_start", source.get("t_start") or 0))
        locator = f"page {where['page']}" if "page" in where else f"{seconds // 60} min {seconds % 60} s"
        title = str(source.get("video") or "Unknown source")[:300]
        if (title, locator) in seen or len(picked) >= MAX_SOURCES:
            continue
        seen.add((title, locator))
        digest = (source.get("provenance") or {}).get("sha256")
        picked.append({"title": title, "locator": locator, "document_identifier": f"videorag:{source.get('kind')}:{source.get('segment_id')}", "content_hash": digest if isinstance(digest, str) and len(digest) == 64 else None})
    return picked


def _from_rag(topic: KnowledgeTopic, items: list[dict[str, Any]], rag_domain: str | None, additions: _Additions) -> tuple[list[dict[str, Any]], list[str]]:
    settings = get_settings()
    warnings: list[str] = []
    editable = [item for item in items if item["editable"]]
    if len(editable) > MAX_RAG_ITEMS:
        warnings.append(f"Only the first {MAX_RAG_ITEMS} of {len(editable)} items were checked. Run it again after reviewing these.")
    questions: list[tuple[str, Any, str]] = [("update", item, f"What is {item['name']} in the context of {topic.name}, and why does it matter? Answer in 2 or 3 plain sentences.{' End with one concrete example of how it shows up, starting Example:' if item['branch'] == 'vulnerabilities' else ''}") for item in editable[:MAX_RAG_ITEMS]]
    questions += [("branch", branch, f"For {topic.name}, what are {ask}? List each as {RAG_VULNERABILITY_LIST_FORMAT if branch == 'vulnerabilities' else RAG_LIST_FORMAT}, one per line.") for branch, ask in RAG_BRANCH_ASK.items()]
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=RAG_WORKERS)
    futures = {pool.submit(videorag.ask, question, rag_domain): (kind, subject) for kind, subject, question in questions}
    done, unfinished = concurrent.futures.wait(futures, timeout=settings.recommendation_timeout_seconds)
    pool.shutdown(wait=False, cancel_futures=True)
    if unfinished:
        warnings.append(f"{len(unfinished)} of {len(questions)} questions did not finish in time. Run it again for the rest.")
    answers, failures = [], []
    for future in done:
        try:
            answers.append((*futures[future], future.result()))
        except ProviderError as exc:
            failures.append(exc.message)
    if failures and not answers:
        raise HTTPException(status_code=503, detail=f"The RAG knowledge DB could not produce recommendations: {failures[0]}")
    if failures:
        warnings.append(f"{len(failures)} questions failed: {failures[0]}")
    recommendations = []
    order = {id(subject): index for index, (_, subject, _) in enumerate(questions)}
    for kind, subject, answer in sorted(answers, key=lambda entry: order[id(entry[1])]):
        label = subject["name"] if kind == "update" else BRANCHES[subject]
        if not answer.get("grounded") or _is_refusal(answer):
            warnings.append(f"{label}: the knowledge DB does not cover this, so it was skipped.")
            continue
        weak, sources = bool(answer.get("weak")), _rag_sources(answer)
        if kind == "update":
            description = _first_sentences(_plain(answer.get("answer", "")), 4 if subject["branch"] == "vulnerabilities" else 3)
            problem = _text_problem(description) if description else "the answer was empty"
            if problem:
                warnings.append(f"{label} was dropped: {problem}.")
            elif description != subject["description"].strip():
                recommendations.append(_update(subject, description, weak=weak, sources=sources))
            continue
        listed = _listed(answer.get("answer", ""))
        if not listed:
            warnings.append(f"{label}: the answer had no list that could be read.")
        for name, description in listed:
            if additions.full(subject):
                warnings.append(f"{label}: only the first {additions.limits[subject]} new topics are shown.")
                break
            problem = additions.reason_to_drop(subject, name, description)
            if problem:
                warnings.append(f"{name} was dropped: {problem}.")
                continue
            additions.accept(subject, name)
            recommendations.append(_addition(subject, name, _first_sentences(description, 4 if subject == "vulnerabilities" else 3), weak=weak, sources=sources))
    return recommendations, warnings


def _apply_checks(reply: dict[str, Any], drafts: list[dict[str, Any]], additions: _Additions) -> tuple[list[dict[str, Any]], list[str]]:
    checks: dict[str, _KimiCheck] = {}
    for value in reply.get("checks") or []:
        try:
            check = _KimiCheck.model_validate(value)
        except ValidationError:
            continue
        checks[check.id] = check
    kept, notes = [], []
    for index, draft in enumerate(drafts):
        check = checks.get(f"draft-{index}")
        if check is None:
            kept.append({**draft, "verification": "unchecked"})
            notes.append(f"Kimi did not check {draft['name']}.")
            continue
        note = check.note.strip()[:MAX_NOTE]
        note = None if not note or _text_problem(note) else note
        if check.verdict == "rejected":
            if draft["kind"] == "add_topic":
                additions.release(draft["branch"])
            notes.append(f"{draft['name']} was dropped: Kimi rejected it{f' ({note})' if note else ''}.")
            continue
        if check.verdict == "confirmed":
            kept.append({**draft, "verification": "confirmed", "verification_note": note})
            continue
        description = (check.description or "").strip()
        problem = _text_problem(description) if description else "it gave no corrected text"
        if problem:
            kept.append({**draft, "verification": "unchecked"})
            notes.append(f"Kimi's correction to {draft['name']} was not used: {problem}.")
            continue
        kept.append({**draft, "description": description, "verification": "corrected", "verification_note": note})
    return kept, notes


def _from_both(topic: KnowledgeTopic, domain: SecurityDomain, items: list[dict[str, Any]], rag_domain: str | None, additions: _Additions, own: set[str]) -> tuple[list[dict[str, Any]], list[str]]:
    drafts: list[dict[str, Any]] = []
    warnings: list[str] = []
    try:
        drafts, warnings = _from_rag(topic, items, rag_domain, additions)
    except HTTPException as exc:
        warnings.append(f"RAG was not used: {exc.detail}.")
    drafted = {draft["ref"] for draft in drafts if draft["ref"]}
    rest = [item for item in items if item["ref"] not in drafted]
    # Only these fields leave for Kimi. Sources stay here.
    sent = [{"id": f"draft-{index}", "branch": BRANCHES[draft["branch"]], "name": draft["name"], "description": draft["description"]} for index, draft in enumerate(drafts)]
    try:
        reply = _ask_kimi(_kimi_prompt(topic, domain, rest, sorted(set(additions.names) - own), additions.room(), sent))
    except HTTPException as exc:
        if not drafts:
            raise
        warnings.append(f"Kimi could not check these, so they are marked not checked: {exc.detail}.")
        return [{**draft, "verification": "unchecked"} for draft in drafts], warnings
    checked, notes = _apply_checks(reply, drafts, additions)
    extra, more = _kimi_items(reply, rest, additions, "kimi_only")
    return checked + extra, warnings + notes + more


def _rag_label(rag_domain: str | None) -> str:
    return f"RAG knowledge DB ({rag_domain or 'all domains'})"


def _gaps(recommendations: list[dict[str, Any]], items: list[dict[str, Any]]) -> list[str]:
    """What the reviewer expected and did not get: a branch left empty, or a weakness with no example."""
    notes = [f"{label} is still empty: nothing came back for it." for branch, label in BRANCHES.items() if not any(entry["branch"] == branch for entry in [*items, *recommendations])]
    return notes + [f"{entry['name']} has no example." for entry in recommendations if entry["branch"] == "vulnerabilities" and "example" not in entry["description"].casefold()]


def recommend(db: Session, topic_id: int, request: RecommendationRequest) -> dict[str, Any]:
    topic, domain, items, grouped = _branch_topic(db, topic_id, request.domain_id)
    parents = db.scalars(select(KnowledgeTopic).join(KnowledgeTopicDomain, KnowledgeTopicDomain.topic_id == KnowledgeTopic.id).where(KnowledgeTopicDomain.domain_id == domain.id)).all()
    own = {item["name"] for item in items}
    domain_names = [item["name"] for key, group in grouped.items() if key[0] == domain.id for item in group] + [item.name for item in parents]
    additions = _Additions(db, domain_names, {item["name"].casefold() for group in grouped.values() for item in group}, items)
    kimi_label, rag_label = f"Kimi ({get_settings().kimi_model})", _rag_label(request.rag_domain)
    if request.source == "kimi":
        reply = _ask_kimi(_kimi_prompt(topic, domain, items, sorted(set(domain_names) - own), additions.room()))
        recommendations, warnings = _kimi_items(reply, items, additions)
        label = kimi_label
    elif request.source == "both":
        recommendations, warnings = _from_both(topic, domain, items, request.rag_domain, additions, own)
        label = f"{rag_label} + {kimi_label}"
    else:
        recommendations, warnings = _from_rag(topic, items, request.rag_domain, additions)
        label = rag_label
    return {"topic_id": topic.id, "topic_name": topic.name, "domain_id": domain.id, "source": request.source, "source_label": label, "recommendations": recommendations, "warnings": warnings + _gaps(recommendations, items)}


def _label(submission: RecommendationSubmission, item: RecommendationItem) -> str:
    kimi, rag = f"Kimi ({get_settings().kimi_model})", _rag_label(submission.rag_domain)
    if submission.source != "both":
        return kimi if submission.source == "kimi" else rag
    label = {"confirmed": f"{rag}, confirmed by {kimi}", "corrected": f"{rag}, corrected by {kimi}", "unchecked": f"{rag}, not checked by Kimi", "kimi_only": kimi}[item.verification]
    return f"{label}. Kimi's note: {item.verification_note}" if item.verification_note else label


def _source_type(submission: RecommendationSubmission, item: RecommendationItem) -> str:
    """Who wrote the text: a Kimi correction is Kimi's wording, even though it keeps the RAG references."""
    if submission.source == "both":
        return "rag" if item.verification in {"confirmed", "unchecked"} else "ai"
    return "ai" if submission.source == "kimi" else "rag"


def _references(submission: RecommendationSubmission, item: RecommendationItem) -> list[dict[str, Any]]:
    kimi = {"source_type": "ai", "title": f"{get_settings().kimi_model} through OpenWebUI", "verification_status": "ai_derived"}
    if submission.source == "kimi":
        return [kimi]
    rag = [{"source_type": "rag", "title": source.title, "locator": source.locator, "document_identifier": source.document_identifier, "content_hash": source.content_hash,
            "access_scope": "private", "is_private": True, "verification_status": "unverified", "metadata": {"rag_domain": submission.rag_domain, "weak_evidence": item.weak}} for source in item.sources]
    return [*rag, kimi] if submission.source == "both" and item.verification != "unchecked" else rag


def _revise_pending(db: Session, proposal_id: int, submission: RecommendationSubmission, item: RecommendationItem, actor: str) -> KnowledgeTopicProposal:
    content = deepcopy(get_proposal(db, proposal_id).proposed_content)
    content["topic"]["description"] = item.description.strip()
    note = f"Recommended by {_label(submission, item)}. For review; not approved or published."
    proposal = review_proposal(db, proposal_id, KnowledgeProposalReview(expected_version=item.expected_version, action="modify", reviewer_note=note, proposed_content=content), actor)
    # The text now comes from this source, so the review screen must say so.
    proposal.source_type = _source_type(submission, item)
    for reference in _references(submission, item):
        db.add(KnowledgeProposalSource(proposal_id=proposal.id, **_source_values(KnowledgeSourceReference.model_validate(reference))))
    db.commit()
    return get_proposal(db, proposal.id)


def _new_proposal(db: Session, topic: KnowledgeTopic, submission: RecommendationSubmission, item: RecommendationItem, actor: str) -> KnowledgeTopicProposal:
    if item.kind == "add_topic":
        payload: dict[str, Any] = {"action": "CREATE_TOPIC", "topic_name": item.name.strip(), "proposed_content": {"topic": {"name": item.name.strip(), "description": item.description.strip(), "aliases": item.aliases}, "placements": [{"domain_id": submission.domain_id, "parent_topic_id": topic.id, "map_branch": item.branch}]}}
    else:
        payload = {"action": "UPDATE_TOPIC", "topic_id": int(item.ref.split(":")[1]), "proposed_content": {"description": item.description.strip()}}
    key = "branch-rec:" + hashlib.sha256(json.dumps({"parent": topic.id, "source": submission.source, **payload}, sort_keys=True).encode()).hexdigest()[:40]
    reason = f"For {topic.name} › {BRANCHES[item.branch]}, for review, not approved or published. Recommended by {_label(submission, item)}"
    return create_proposal(db, KnowledgeProposalCreate.model_validate({"schema_version": "1.0", "source_type": _source_type(submission, item), "submit_for_review": True, "change_reason": reason[:500], "references": _references(submission, item), **payload}), actor, key)


def submit_recommendations(db: Session, topic_id: int, submission: RecommendationSubmission, actor: str) -> dict[str, Any]:
    topic, _, items, _ = _branch_topic(db, topic_id, submission.domain_id)
    allowed = {item["ref"]: item for item in items if item["editable"]}
    proposals, done, errors = [], [], []
    for index, item in enumerate(submission.items):
        problem = _text_problem(f"{item.name} {item.description}")
        target = allowed.get(item.ref) if item.kind == "update_description" else None
        if item.kind == "update_description" and (target is None or target["branch"] != item.branch):
            problem = "it no longer matches an item that can be revised"
        elif target and target["version"] is not None and item.expected_version is None:
            problem = "it has no proposal version, so a later edit could be overwritten"
        if problem:
            errors.append(f"{item.name}: {problem}.")
            continue
        try:
            if target and item.ref.startswith("proposal:"):
                proposal = _revise_pending(db, int(item.ref.split(":")[1]), submission, item, actor)
            else:
                proposal = _new_proposal(db, topic, submission, item, actor)
        except (HTTPException, ValidationError) as exc:
            db.rollback()
            detail = getattr(exc, "detail", None) or "the content is not valid"
            errors.append(f"{item.name}: {detail.get('message') if isinstance(detail, dict) else detail}")
            continue
        proposals.append(proposal)
        done.append(index)
    return {"proposals": proposals, "done": done, "errors": errors}
