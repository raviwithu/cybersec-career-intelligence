from __future__ import annotations

import re
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .knowledge_contract_schemas import RELATIONSHIP_TYPES, SECTION_TYPES, _clean_text
from .knowledge_map_service import _reachable_domains
from .knowledge_topic_service import snapshot
from .models import (
    MAP_BRANCHES,
    CareerLevel,
    Industry,
    KnowledgeTopic,
    KnowledgeTopicDomain,
    KnowledgeTopicLevel,
    KnowledgeTopicRelationship,
    KnowledgeTopicSection,
    KnowledgeTopicSectionVersion,
    KnowledgeTopicVersion,
    SecurityDomain,
)

# Knowledge map changes travel through the knowledge contract as proposals (D3). This module validates their
# payloads, captures the live state they would change, applies them inside the publish transaction, and previews them.

MAP_ACTIONS = (
    "PLACE_TOPIC", "UNPLACE_TOPIC", "MOVE_TOPIC", "REORDER_TOPICS", "SET_PARENT_TOPIC",
    "REMOVE_TOPIC_RELATIONSHIP", "DEACTIVATE_TOPIC", "UPDATE_CAREER_LEVELS", "RESTORE_VERSION",
)
Branch = Literal["foundations", "security", "vulnerabilities"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Placement(_Strict):
    domain_id: int = Field(ge=1)
    map_branch: Branch
    display_order: int | None = Field(default=None, ge=0, le=100_000)
    # How this shared topic applies in this domain. Omitted or null keeps the current note; "" clears it.
    context_note: str | None = Field(default=None, max_length=2000)

    @field_validator("context_note")
    @classmethod
    def clean_note(cls, value: str | None) -> str | None:
        return None if value is None else _clean_text(value)


class DomainRef(_Strict):
    domain_id: int = Field(ge=1)


class MoveTopic(_Strict):
    source: DomainRef = Field(alias="from")
    target: Placement = Field(alias="to")


class ReorderTopics(_Strict):
    domain_id: int = Field(ge=1)
    map_branch: Branch
    ordered_topic_ids: list[int] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_ids(self):
        if len(set(self.ordered_topic_ids)) != len(self.ordered_topic_ids):
            raise ValueError("ordered_topic_ids must not repeat a topic")
        return self


class SetParentTopic(_Strict):
    parent_topic_id: int | None = Field(ge=1)


class RemoveRelationship(_Strict):
    target_topic_id: int = Field(ge=1)
    relationship_type: Literal[RELATIONSHIP_TYPES]


class DeactivateTopic(_Strict):
    reason: str = Field(min_length=1, max_length=500)


class LevelRow(_Strict):
    career_level_id: int = Field(ge=1)
    industry_id: int | None = Field(default=None, ge=1)
    expectation: str = Field(default="", max_length=4000)
    practical_capability: str = Field(default="", max_length=4000)


class UpdateCareerLevels(_Strict):
    levels: list[LevelRow] = Field(min_length=1, max_length=60)

    @model_validator(mode="after")
    def unique_levels(self):
        keys = [(row.career_level_id, row.industry_id) for row in self.levels]
        if len(set(keys)) != len(keys):
            raise ValueError("Each career level and industry pair may appear once")
        return self


class RestoreVersion(_Strict):
    target: Literal["topic", "section"]
    section_type: Literal[SECTION_TYPES] | None = None
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def section_needs_type(self):
        if (self.target == "section") != (self.section_type is not None):
            raise ValueError("section_type is required when restoring a section, and only then")
        return self


class CreatePlacements(BaseModel):
    placements: list[Placement] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def one_per_domain(self):
        domains = [item.domain_id for item in self.placements]
        if len(set(domains)) != len(domains):
            raise ValueError("A topic has at most one branch per domain")
        return self


PAYLOADS: dict[str, type[BaseModel]] = {
    "PLACE_TOPIC": Placement, "UNPLACE_TOPIC": DomainRef, "MOVE_TOPIC": MoveTopic, "REORDER_TOPICS": ReorderTopics,
    "SET_PARENT_TOPIC": SetParentTopic, "REMOVE_TOPIC_RELATIONSHIP": RemoveRelationship, "DEACTIVATE_TOPIC": DeactivateTopic,
    "UPDATE_CAREER_LEVELS": UpdateCareerLevels, "RESTORE_VERSION": RestoreVersion,
}


def _without_empty_note(placement: dict[str, Any]) -> dict[str, Any]:
    # A missing context note means "keep the current note"; leave the key out so stored proposals stay unchanged.
    return {key: value for key, value in placement.items() if key != "context_note" or value is not None}


def validate_map_payload(action: str, content: dict[str, Any]) -> dict[str, Any]:
    """Checks the shape of a map action payload (or CREATE_TOPIC placements). Raises HTTP 422; returns normalised content."""
    try:
        if action == "CREATE_TOPIC":
            if "placements" not in content:
                return content
            return {**content, "placements": [_without_empty_note(item) for item in CreatePlacements.model_validate({"placements": content["placements"]}).model_dump()["placements"]]}
        normalised = PAYLOADS[action].model_validate(content).model_dump(by_alias=True)
        if action == "PLACE_TOPIC":
            return _without_empty_note(normalised)
        if action == "MOVE_TOPIC":
            return {**normalised, "to": _without_empty_note(normalised["to"])}
        return normalised
    except ValidationError as error:
        first = error.errors()[0]
        location = ".".join(str(part) for part in first["loc"])
        raise HTTPException(status_code=422, detail=f"Invalid {action} content: {location + ': ' if location else ''}{first['msg']}") from error


# ---- live state -------------------------------------------------------------------------------------------------

def _link(db: Session, topic_id: int, domain_id: int, *, lock: bool = False) -> KnowledgeTopicDomain | None:
    query = select(KnowledgeTopicDomain).where(KnowledgeTopicDomain.topic_id == topic_id, KnowledgeTopicDomain.domain_id == domain_id)
    return db.scalar(query.with_for_update() if lock else query)


def _placement_state(link: KnowledgeTopicDomain | None) -> dict[str, Any] | None:
    if link is None or link.map_branch is None:
        return None
    return {"domain_id": link.domain_id, "map_branch": link.map_branch, "display_order": link.display_order, "context_note": link.context_note}


def _placements(db: Session, topic_id: int) -> list[dict[str, Any]]:
    rows = db.scalars(select(KnowledgeTopicDomain).where(KnowledgeTopicDomain.topic_id == topic_id, KnowledgeTopicDomain.map_branch.is_not(None)).order_by(KnowledgeTopicDomain.domain_id)).all()
    return [_placement_state(row) for row in rows]


def branch_members(db: Session, domain_id: int, branch: str, *, include_topic_id: int | None = None) -> list[dict[str, Any]]:
    """Topics the public map shows in one branch, in order. include_topic_id also lists a topic that publishing would publish."""
    visible = (KnowledgeTopic.publication_status == "published") if include_topic_id is None else ((KnowledgeTopic.publication_status == "published") | (KnowledgeTopic.id == include_topic_id))
    rows = db.execute(
        select(KnowledgeTopic.id, KnowledgeTopic.name)
        .join(KnowledgeTopicDomain, KnowledgeTopicDomain.topic_id == KnowledgeTopic.id)
        .where(KnowledgeTopicDomain.domain_id == domain_id, KnowledgeTopicDomain.map_branch == branch, KnowledgeTopic.is_active.is_(True), visible)
        .order_by(KnowledgeTopicDomain.display_order, func.lower(KnowledgeTopic.name))
    ).all()
    return [{"topic_id": topic_id, "name": name} for topic_id, name in rows]


def map_snapshot(db: Session, topic: KnowledgeTopic) -> dict[str, Any]:
    return {**snapshot(topic), "placements": _placements(db, topic.id)}


def _level_state(db: Session, topic_id: int, rows: list[dict[str, Any]]) -> list[dict[str, Any] | None]:
    states = []
    for row in rows:
        item = db.scalar(select(KnowledgeTopicLevel).where(KnowledgeTopicLevel.topic_id == topic_id, KnowledgeTopicLevel.career_level_id == row["career_level_id"], KnowledgeTopicLevel.industry_id.is_(None) if row.get("industry_id") is None else KnowledgeTopicLevel.industry_id == row["industry_id"]))
        states.append(None if item is None else {"career_level_id": item.career_level_id, "industry_id": item.industry_id, "expectation": item.expectation, "practical_capability": item.practical_capability})
    return states


def current_state(db: Session, action: str, topic: KnowledgeTopic | None, content: dict[str, Any]) -> dict[str, Any] | None:
    """The live state a proposal would change. Stored as original_content and compared again at publish."""
    if topic is None:
        return None
    if action in {"PLACE_TOPIC", "UNPLACE_TOPIC"}:
        return {"placement": _placement_state(_link(db, topic.id, content["domain_id"]))}
    if action == "MOVE_TOPIC":
        return {"from": _placement_state(_link(db, topic.id, content["from"]["domain_id"])), "to": _placement_state(_link(db, topic.id, content["to"]["domain_id"]))}
    if action == "REORDER_TOPICS":
        return {"members": [item["topic_id"] for item in branch_members(db, content["domain_id"], content["map_branch"])]}
    if action == "SET_PARENT_TOPIC":
        return {"parent_topic_id": topic.parent_topic_id}
    if action == "REMOVE_TOPIC_RELATIONSHIP":
        return {"exists": _relationship(db, topic.id, content) is not None}
    if action == "DEACTIVATE_TOPIC":
        return {"is_active": topic.is_active, "placements": _placements(db, topic.id)}
    if action == "UPDATE_CAREER_LEVELS":
        return {"levels": _level_state(db, topic.id, content["levels"])}
    if action == "RESTORE_VERSION":
        if content["target"] == "section":
            section = _section_row(db, topic.id, content["section_type"])
            return {"section_type": content["section_type"], "published_version": section.published_version if section else 0, "content": section.published_content if section else None}
        return {"topic": map_snapshot(db, topic)}
    return None


# ---- validation ---------------------------------------------------------------------------------------------------

def _relationship(db: Session, topic_id: int, content: dict[str, Any]) -> KnowledgeTopicRelationship | None:
    return db.scalar(select(KnowledgeTopicRelationship).where(KnowledgeTopicRelationship.source_topic_id == topic_id, KnowledgeTopicRelationship.target_topic_id == content["target_topic_id"], KnowledgeTopicRelationship.relationship_type == content["relationship_type"]))


def _section_row(db: Session, topic_id: int, section_type: str) -> KnowledgeTopicSection | None:
    return db.scalar(select(KnowledgeTopicSection).where(KnowledgeTopicSection.topic_id == topic_id, KnowledgeTopicSection.section_type == section_type))


def stored_section_version(db: Session, topic_id: int, section_type: str, version: int) -> KnowledgeTopicSectionVersion | None:
    return db.scalar(select(KnowledgeTopicSectionVersion).join(KnowledgeTopicSection, KnowledgeTopicSection.id == KnowledgeTopicSectionVersion.section_id).where(KnowledgeTopicSection.topic_id == topic_id, KnowledgeTopicSection.section_type == section_type, KnowledgeTopicSectionVersion.version == version))


def _stored_topic_version(db: Session, topic_id: int, version: int) -> KnowledgeTopicVersion | None:
    return db.scalar(select(KnowledgeTopicVersion).where(KnowledgeTopicVersion.topic_id == topic_id, KnowledgeTopicVersion.version == version))


def _require_domain(db: Session, domain_id: int) -> SecurityDomain:
    domain = _reachable_domains(db).get(domain_id)
    if domain is None:
        raise HTTPException(status_code=409, detail=f"Security domain {domain_id} is not active on the map")
    return domain


def _require_parent_allowed(db: Session, topic_id: int, parent_id: int | None) -> None:
    if parent_id is None:
        return
    if parent_id == topic_id:
        raise HTTPException(status_code=422, detail="A topic cannot be its own parent")
    parent = db.get(KnowledgeTopic, parent_id)
    if parent is None or not parent.is_active:
        raise HTTPException(status_code=409, detail="The parent topic must exist and be active")
    seen: set[int] = set()
    current = parent
    while current is not None and current.id not in seen:
        if current.id == topic_id:
            raise HTTPException(status_code=409, detail="This parent would create a cycle in the topic hierarchy")
        seen.add(current.id)
        current = db.get(KnowledgeTopic, current.parent_topic_id) if current.parent_topic_id else None


def validate_map_change(db: Session, action: str, topic: KnowledgeTopic, content: dict[str, Any]) -> None:
    """Rules checked when a proposal is created, modified and again at publish, because the map may have changed."""
    if action != "RESTORE_VERSION" and not topic.is_active:
        raise HTTPException(status_code=409, detail="The knowledge topic is inactive")
    if action == "PLACE_TOPIC":
        _require_domain(db, content["domain_id"])
    elif action == "UNPLACE_TOPIC":
        if _placement_state(_link(db, topic.id, content["domain_id"])) is None:
            raise HTTPException(status_code=409, detail="The topic is not placed in this domain")
    elif action == "MOVE_TOPIC":
        source = _placement_state(_link(db, topic.id, content["from"]["domain_id"]))
        if source is None:
            raise HTTPException(status_code=409, detail="The topic is not placed in the source domain")
        _require_domain(db, content["to"]["domain_id"])
        if content["from"]["domain_id"] == content["to"]["domain_id"] and source["map_branch"] == content["to"]["map_branch"]:
            raise HTTPException(status_code=422, detail="The move does not change the placement")
    elif action == "REORDER_TOPICS":
        _require_domain(db, content["domain_id"])
        members = [item["topic_id"] for item in branch_members(db, content["domain_id"], content["map_branch"])]
        if sorted(members) != sorted(content["ordered_topic_ids"]):
            raise HTTPException(status_code=409, detail="The order must list exactly the topics currently in this branch")
    elif action == "SET_PARENT_TOPIC":
        _require_parent_allowed(db, topic.id, content["parent_topic_id"])
    elif action == "REMOVE_TOPIC_RELATIONSHIP":
        if _relationship(db, topic.id, content) is None:
            raise HTTPException(status_code=409, detail="That relationship does not exist")
    elif action == "UPDATE_CAREER_LEVELS":
        for row in content["levels"]:
            level = db.get(CareerLevel, row["career_level_id"])
            if level is None or not level.is_active:
                raise HTTPException(status_code=409, detail=f"Career level {row['career_level_id']} is not active")
            if row.get("industry_id") is not None:
                industry = db.get(Industry, row["industry_id"])
                if industry is None or not industry.is_active:
                    raise HTTPException(status_code=409, detail=f"Industry {row['industry_id']} is not active")
    elif action == "RESTORE_VERSION":
        if content["target"] == "section":
            if stored_section_version(db, topic.id, content["section_type"], content["version"]) is None:
                raise HTTPException(status_code=404, detail="That section version was not found")
        else:
            stored = _stored_topic_version(db, topic.id, content["version"])
            if stored is None:
                raise HTTPException(status_code=404, detail="That topic version was not found")
            _require_parent_allowed(db, topic.id, stored.snapshot.get("parent_topic_id"))
            for placement in stored.snapshot.get("placements") or []:
                _require_domain(db, placement["domain_id"])


def validate_create_placements(db: Session, content: dict[str, Any]) -> None:
    for placement in content.get("placements") or []:
        _require_domain(db, placement["domain_id"])


# Duplicate detection for CREATE_TOPIC: normalised name, slug, topic_key and aliases of every existing topic.
def _normal(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


def find_duplicate_topic(db: Session, candidates: list[str]) -> KnowledgeTopic | None:
    wanted = {_normal(value) for value in candidates if _normal(value)}
    if not wanted:
        return None
    for topic in db.scalars(select(KnowledgeTopic).order_by(KnowledgeTopic.id)).all():
        names = {_normal(topic.name), _normal(topic.slug), _normal(topic.topic_key), *(_normal(alias) for alias in (topic.aliases or []))}
        if wanted & names:
            return topic
    return None


def require_no_duplicate(db: Session, name: str, topic_key: str, content: dict[str, Any]) -> None:
    metadata = content.get("topic") if isinstance(content.get("topic"), dict) else content
    aliases = [alias for alias in metadata.get("aliases", []) if isinstance(alias, str)]
    duplicate = find_duplicate_topic(db, [name, topic_key, metadata.get("slug") or "", *aliases])
    if duplicate is not None:
        raise HTTPException(status_code=409, detail={
            "message": f"A topic matching this name, key or alias already exists: {duplicate.name}. Propose PLACE_TOPIC or a section update for it instead.",
            "existing_topic_id": duplicate.id,
            "existing_topic_key": duplicate.topic_key or duplicate.slug,
        })


# ---- applying (inside the publish transaction; never commits) -----------------------------------------------------

def _next_order(db: Session, domain_id: int, branch: str) -> int:
    current = db.scalar(select(func.max(KnowledgeTopicDomain.display_order)).where(KnowledgeTopicDomain.domain_id == domain_id, KnowledgeTopicDomain.map_branch == branch))
    return 0 if current is None else current + 1


def place(db: Session, topic: KnowledgeTopic, domain_id: int, branch: str, display_order: int | None, context_note: str | None = None) -> None:
    link = _link(db, topic.id, domain_id, lock=True)
    order = display_order if display_order is not None else (link.display_order if link is not None and link.map_branch == branch else _next_order(db, domain_id, branch))
    if link is None:
        # Placing in a new domain creates the domain link, which also lists the topic for that domain in Career Readiness (D2).
        link = KnowledgeTopicDomain(topic_id=topic.id, domain_id=domain_id)
        topic.domains.append(link)
    link.map_branch = branch
    link.display_order = order
    if context_note is not None:
        link.context_note = context_note or None
    db.flush()


def unplace(db: Session, topic: KnowledgeTopic, domain_id: int) -> None:
    link = _link(db, topic.id, domain_id, lock=True)
    if link is not None:
        link.map_branch = None  # The domain link stays (D2).
    db.flush()


def _set_levels(db: Session, topic: KnowledgeTopic, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        item = next((level for level in topic.level_expectations if level.career_level_id == row["career_level_id"] and level.industry_id == row.get("industry_id")), None)
        if item is None:
            item = KnowledgeTopicLevel(career_level_id=row["career_level_id"], industry_id=row.get("industry_id"), display_order=row.get("display_order", 0))
            topic.level_expectations.append(item)
        item.expectation = row.get("expectation", "")
        item.practical_capability = row.get("practical_capability", "")


def _restore_topic(db: Session, topic: KnowledgeTopic, stored: dict[str, Any]) -> None:
    for key in ("name", "description", "category_id", "display_order", "parent_topic_id", "aliases"):
        if key in stored:
            setattr(topic, key, stored[key])
    if "is_active" in stored:
        topic.is_active = bool(stored["is_active"])
    if "placements" in stored:
        wanted = {item["domain_id"]: item for item in stored["placements"]}
        for current in _placements(db, topic.id):
            if current["domain_id"] not in wanted:
                unplace(db, topic, current["domain_id"])
        for item in wanted.values():
            # Snapshots taken before context notes existed have no key: leave the current note alone.
            place(db, topic, item["domain_id"], item["map_branch"], item.get("display_order"), (item["context_note"] or "") if "context_note" in item else None)
    if "level_expectations" in stored:
        keep = {(row["career_level_id"], row.get("industry_id")) for row in stored["level_expectations"]}
        for item in list(topic.level_expectations):
            if (item.career_level_id, item.industry_id) not in keep:
                topic.level_expectations.remove(item)
        _set_levels(db, topic, stored["level_expectations"])


def apply_map_change(db: Session, action: str, topic: KnowledgeTopic, content: dict[str, Any]) -> None:
    """Writes one map change to the live tables. The caller owns the transaction."""
    db.refresh(topic, with_for_update=True)
    if action == "PLACE_TOPIC":
        place(db, topic, content["domain_id"], content["map_branch"], content.get("display_order"), content.get("context_note"))
    elif action == "UNPLACE_TOPIC":
        unplace(db, topic, content["domain_id"])
    elif action == "MOVE_TOPIC":
        unplace(db, topic, content["from"]["domain_id"])
        place(db, topic, content["to"]["domain_id"], content["to"]["map_branch"], content["to"].get("display_order"), content["to"].get("context_note"))
    elif action == "REORDER_TOPICS":
        for index, topic_id in enumerate(content["ordered_topic_ids"]):
            link = _link(db, topic_id, content["domain_id"], lock=True)
            link.display_order = index
    elif action == "SET_PARENT_TOPIC":
        topic.parent_topic_id = content["parent_topic_id"]
    elif action == "REMOVE_TOPIC_RELATIONSHIP":
        db.delete(_relationship(db, topic.id, content))
    elif action == "DEACTIVATE_TOPIC":
        topic.is_active = False
    elif action == "UPDATE_CAREER_LEVELS":
        _set_levels(db, topic, content["levels"])
    elif action == "RESTORE_VERSION" and content["target"] == "topic":
        _restore_topic(db, topic, _stored_topic_version(db, topic.id, content["version"]).snapshot)
    db.flush()


def apply_create_placements(db: Session, topic: KnowledgeTopic, content: dict[str, Any]) -> None:
    for item in content.get("placements") or []:
        place(db, topic, item["domain_id"], item["map_branch"], item.get("display_order"), item.get("context_note"))


# ---- preview -------------------------------------------------------------------------------------------------------

def affected_branches(db: Session, action: str, topic: KnowledgeTopic | None, content: dict[str, Any]) -> list[tuple[int, str]]:
    pairs: list[tuple[int, str]] = []

    def add(domain_id: int, branch: str | None) -> None:
        if branch and (domain_id, branch) not in pairs:
            pairs.append((domain_id, branch))

    def existing(domain_id: int) -> str | None:
        state = _placement_state(_link(db, topic.id, domain_id)) if topic is not None else None
        return state["map_branch"] if state else None

    if action == "CREATE_TOPIC":
        for item in content.get("placements") or []:
            add(item["domain_id"], item["map_branch"])
    elif action == "PLACE_TOPIC":
        add(content["domain_id"], existing(content["domain_id"]))
        add(content["domain_id"], content["map_branch"])
    elif action == "UNPLACE_TOPIC":
        add(content["domain_id"], existing(content["domain_id"]))
    elif action == "MOVE_TOPIC":
        add(content["from"]["domain_id"], existing(content["from"]["domain_id"]))
        add(content["to"]["domain_id"], existing(content["to"]["domain_id"]))
        add(content["to"]["domain_id"], content["to"]["map_branch"])
    elif action == "REORDER_TOPICS":
        add(content["domain_id"], content["map_branch"])
    elif action == "DEACTIVATE_TOPIC" and topic is not None:
        for item in _placements(db, topic.id):
            add(item["domain_id"], item["map_branch"])
    elif action == "RESTORE_VERSION" and content.get("target") == "topic" and topic is not None:
        for item in _placements(db, topic.id):
            add(item["domain_id"], item["map_branch"])
        stored = _stored_topic_version(db, topic.id, content["version"])
        for item in (stored.snapshot.get("placements") if stored else None) or []:
            add(item["domain_id"], item["map_branch"])
    return pairs


def describe_branches(db: Session, pairs: list[tuple[int, str]], *, include_topic_id: int | None = None) -> dict[tuple[int, str], list[dict[str, Any]]]:
    return {pair: branch_members(db, pair[0], pair[1], include_topic_id=include_topic_id) for pair in pairs}


def branch_label(db: Session, domain_id: int, branch: str) -> dict[str, Any]:
    domain = db.get(SecurityDomain, domain_id)
    return {"domain_id": domain_id, "domain_name": domain.name if domain else f"Domain {domain_id}", "map_branch": branch, "label": MAP_BRANCHES.get(branch, branch)}
