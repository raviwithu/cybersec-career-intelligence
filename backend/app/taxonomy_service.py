from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, selectinload

from .models import (
    CareerLevel,
    CareerLevelAlias,
    Competency,
    CompetencyCategory,
    CompetencyCategoryAlias,
    DomainLevelExpectation,
    DraftExpectation,
    Industry,
    IndustryAlias,
    ResearchFinding,
    ResearchFindingDomain,
    ResearchFindingIndustry,
    SecurityDomain,
    SecurityDomainAlias,
    TaxonomyChangeHistory,
)
from .taxonomy_schemas import TaxonomyAliasInput, TaxonomyCreate, TaxonomyEntryResponse, TaxonomyImpactResponse, TaxonomyType, TaxonomyUpdate


TYPE_MODELS = {
    "domain": SecurityDomain,
    "industry": Industry,
    "career_level": CareerLevel,
    "category": CompetencyCategory,
}
ALIAS_MODELS = {
    "domain": (SecurityDomainAlias, "domain_id", "domain"),
    "industry": (IndustryAlias, "industry_id", "industry"),
    "career_level": (CareerLevelAlias, "career_level_id", "career_level"),
    "category": (CompetencyCategoryAlias, "category_id", "category"),
}


def normalize(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return value or "taxonomy-entry"


def model_for(taxonomy_type: str):
    if taxonomy_type not in TYPE_MODELS:
        raise HTTPException(status_code=422, detail=f"Unsupported taxonomy type '{taxonomy_type}'")
    return TYPE_MODELS[taxonomy_type]


def get_entry(db: Session, taxonomy_type: str, entry_id: int):
    item = db.get(model_for(taxonomy_type), entry_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"{taxonomy_type} taxonomy entry {entry_id} was not found")
    return item


def aliases_for(item, taxonomy_type: str) -> list[dict[str, Any]]:
    return [
        {"alias": alias.alias, "requires_context": alias.requires_context, "context_hint": alias.context_hint}
        for alias in sorted(getattr(item, "aliases", []), key=lambda value: value.alias.casefold())
    ]


def dependency_counts(db: Session, taxonomy_type: str, item_id: int) -> dict[str, int]:
    if taxonomy_type == "domain":
        return {
            "children": db.scalar(select(func.count(SecurityDomain.id)).where(SecurityDomain.parent_id == item_id)) or 0,
            "published_expectations": db.scalar(select(func.count(DomainLevelExpectation.id)).where(DomainLevelExpectation.domain_id == item_id)) or 0,
            "research_findings": db.scalar(select(func.count(ResearchFinding.id)).where(ResearchFinding.domain_id == item_id)) or 0,
            "research_domain_links": db.scalar(select(func.count(ResearchFindingDomain.finding_id)).where(ResearchFindingDomain.domain_id == item_id)) or 0,
            "draft_expectations": db.scalar(select(func.count(DraftExpectation.id)).where(DraftExpectation.domain_id == item_id)) or 0,
        }
    if taxonomy_type == "industry":
        return {
            "children": db.scalar(select(func.count(Industry.id)).where(Industry.parent_id == item_id)) or 0,
            "published_expectations": db.scalar(select(func.count(DomainLevelExpectation.id)).where(DomainLevelExpectation.industry_id == item_id)) or 0,
            "research_findings": db.scalar(select(func.count(ResearchFinding.id)).where(ResearchFinding.primary_industry_id == item_id)) or 0,
            "research_industry_links": db.scalar(select(func.count(ResearchFindingIndustry.finding_id)).where(ResearchFindingIndustry.industry_id == item_id)) or 0,
            "draft_expectations": db.scalar(select(func.count(DraftExpectation.id)).where(DraftExpectation.industry_id == item_id)) or 0,
        }
    if taxonomy_type == "career_level":
        return {
            "published_expectations": db.scalar(select(func.count(DomainLevelExpectation.id)).where(DomainLevelExpectation.career_level_id == item_id)) or 0,
            "research_findings": db.scalar(select(func.count(ResearchFinding.id)).where(ResearchFinding.career_level_id == item_id)) or 0,
            "draft_expectations": db.scalar(select(func.count(DraftExpectation.id)).where(DraftExpectation.career_level_id == item_id)) or 0,
        }
    return {
        "competencies": db.scalar(select(func.count(Competency.id)).where(Competency.category_id == item_id)) or 0,
        "research_findings": db.scalar(select(func.count(ResearchFinding.id)).where(ResearchFinding.category_id == item_id)) or 0,
    }


def serialize(item, taxonomy_type: str, db: Session, include_dependencies: bool = True) -> dict[str, Any]:
    parent = getattr(item, "parent", None)
    return {
        "id": item.id,
        "taxonomy_type": taxonomy_type,
        "name": item.name,
        "slug": item.slug,
        "description": item.description or "",
        "parent_id": getattr(item, "parent_id", None),
        "parent_name": parent.name if parent else None,
        "career_track": getattr(item, "career_track", None),
        "display_order": item.display_order,
        "is_active": item.is_active,
        "aliases": aliases_for(item, taxonomy_type),
        "children": [serialize(child, taxonomy_type, db, include_dependencies=False) for child in sorted(getattr(item, "children", []), key=lambda value: (value.display_order, value.name.casefold()))] if taxonomy_type in {"domain", "industry"} else [],
        "dependencies": dependency_counts(db, taxonomy_type, item.id) if include_dependencies else {},
        "created_at": getattr(item, "created_at", None),
        "updated_at": getattr(item, "updated_at", None),
    }


def snapshot(item, taxonomy_type: str, db: Session) -> dict[str, Any]:
    data = serialize(item, taxonomy_type, db, include_dependencies=False)
    data.pop("children", None)
    data.pop("dependencies", None)
    return jsonable_encoder(data)


def _alias_model(taxonomy_type: str):
    return ALIAS_MODELS[taxonomy_type]


def validate_aliases(db: Session, taxonomy_type: str, aliases: Iterable[TaxonomyAliasInput], current_id: int | None = None) -> list[dict[str, Any]]:
    values = []
    seen: set[str] = set()
    model, owner_key, _ = _alias_model(taxonomy_type)
    entry_model = model_for(taxonomy_type)
    for item in aliases:
        alias = item.alias.strip()
        normalized = normalize(alias)
        if not normalized or normalized in seen:
            raise HTTPException(status_code=422, detail=f"Duplicate alias '{alias}'")
        seen.add(normalized)
        canonical = db.scalar(select(entry_model).where(func.lower(entry_model.name) == normalized))
        if canonical is not None and canonical.id != current_id:
            raise HTTPException(status_code=409, detail=f"Alias '{alias}' conflicts with taxonomy name '{canonical.name}'")
        existing = db.scalar(select(model).where(model.normalized_alias == normalized))
        if existing is not None and getattr(existing, owner_key) != current_id:
            raise HTTPException(status_code=409, detail=f"Alias '{alias}' is already assigned to another {taxonomy_type}")
        values.append({"alias": alias, "normalized_alias": normalized, "requires_context": item.requires_context, "context_hint": item.context_hint})
    return values


def validate_parent(db: Session, taxonomy_type: str, item_id: int | None, parent_id: int | None) -> None:
    if taxonomy_type not in {"domain", "industry"} and parent_id is not None:
        raise HTTPException(status_code=422, detail=f"{taxonomy_type} entries cannot have a parent")
    if parent_id is None:
        return
    parent = get_entry(db, taxonomy_type, parent_id)
    if item_id is None:
        return
    if parent.id == item_id:
        raise HTTPException(status_code=422, detail="An entry cannot be its own parent")
    current = parent
    visited: set[int] = set()
    while current is not None:
        if current.id in visited:
            raise HTTPException(status_code=422, detail="The existing hierarchy contains a cycle")
        visited.add(current.id)
        if current.id == item_id:
            raise HTTPException(status_code=422, detail="Parent selection would create a circular hierarchy")
        current = getattr(current, "parent", None)


def ensure_unique_fields(db: Session, taxonomy_type: str, name: str, slug: str, current_id: int | None = None) -> None:
    model = model_for(taxonomy_type)
    name_match = db.scalar(select(model).where(func.lower(model.name) == normalize(name)))
    if name_match is not None and name_match.id != current_id:
        raise HTTPException(status_code=409, detail=f"A {taxonomy_type} named '{name}' already exists")
    slug_match = db.scalar(select(model).where(func.lower(model.slug) == slug.casefold()))
    if slug_match is not None and slug_match.id != current_id:
        raise HTTPException(status_code=409, detail=f"Slug '{slug}' is already in use")


def record_history(db: Session, taxonomy_type: str, item_id: int, action: str, previous: dict | None, updated: dict | None, actor: str, source_id: int | None = None, target_id: int | None = None) -> None:
    db.add(TaxonomyChangeHistory(
        taxonomy_type=taxonomy_type,
        entry_id=item_id,
        action=action,
        previous_values=previous,
        updated_values=updated,
        actor=actor,
        merge_source_id=source_id,
        merge_target_id=target_id,
        created_at=datetime.now(timezone.utc),
    ))


def write_aliases(db: Session, taxonomy_type: str, item, aliases: list[TaxonomyAliasInput]) -> None:
    model, owner_key, _ = _alias_model(taxonomy_type)
    values = validate_aliases(db, taxonomy_type, aliases, item.id)
    for existing in list(getattr(item, "aliases", [])):
        db.delete(existing)
    db.flush()
    for value in values:
        db.add(model(**{owner_key: item.id, **value}))


def create_entry(db: Session, taxonomy_type: str, payload: TaxonomyCreate, actor: str):
    model = model_for(taxonomy_type)
    slug = slugify(payload.slug or payload.name)
    ensure_unique_fields(db, taxonomy_type, payload.name.strip(), slug)
    validate_parent(db, taxonomy_type, None, payload.parent_id)
    alias_values = validate_aliases(db, taxonomy_type, payload.aliases)
    values = {
        "name": payload.name.strip(), "slug": slug, "description": payload.description.strip(),
        "display_order": payload.display_order, "is_active": payload.is_active,
    }
    if taxonomy_type in {"domain", "industry"}:
        values["parent_id"] = payload.parent_id
    if taxonomy_type == "career_level":
        values["career_track"] = payload.career_track
    item = model(**values)
    db.add(item)
    db.flush()
    alias_model, owner_key, _ = _alias_model(taxonomy_type)
    for value in alias_values:
        db.add(alias_model(**{owner_key: item.id, **value}))
    record_history(db, taxonomy_type, item.id, "created", None, snapshot(item, taxonomy_type, db), actor)
    db.commit()
    db.refresh(item)
    return item


def update_entry(db: Session, taxonomy_type: str, entry_id: int, payload: TaxonomyUpdate, actor: str):
    item = get_entry(db, taxonomy_type, entry_id)
    if payload.expected_updated_at and item.updated_at and payload.expected_updated_at != item.updated_at:
        raise HTTPException(status_code=409, detail="This taxonomy entry changed in another session; reload it before saving")
    previous = snapshot(item, taxonomy_type, db)
    values = payload.model_dump(exclude_unset=True, exclude={"aliases", "expected_updated_at"})
    allowed_fields = {"name", "slug", "description", "display_order", "is_active"}
    if taxonomy_type in {"domain", "industry"}:
        allowed_fields.add("parent_id")
    if taxonomy_type == "career_level":
        allowed_fields.add("career_track")
    values = {key: value for key, value in values.items() if key in allowed_fields}
    if "name" in values:
        values["name"] = values["name"].strip()
    slug = values.get("slug", item.slug)
    if slug is None:
        slug = slugify(values.get("name", item.name))
    slug = slugify(slug)
    ensure_unique_fields(db, taxonomy_type, values.get("name", item.name), slug, item.id)
    validate_parent(db, taxonomy_type, item.id, values.get("parent_id", item.parent_id if taxonomy_type in {"domain", "industry"} else None))
    for key, value in values.items():
        if key == "parent_id" and taxonomy_type not in {"domain", "industry"}:
            continue
        setattr(item, key, slug if key == "slug" else value)
    if payload.aliases is not None:
        write_aliases(db, taxonomy_type, item, payload.aliases)
    db.flush()
    record_history(db, taxonomy_type, item.id, "updated", previous, snapshot(item, taxonomy_type, db), actor)
    db.commit()
    db.refresh(item)
    return item


def impact(db: Session, taxonomy_type: str, entry_id: int) -> TaxonomyImpactResponse:
    item = get_entry(db, taxonomy_type, entry_id)
    dependencies = dependency_counts(db, taxonomy_type, entry_id)
    blockers = []
    if dependencies.get("children"):
        blockers.append("Child entries must be moved before permanent deletion.")
    if any(value for key, value in dependencies.items() if key != "children"):
        blockers.append("Published or historical records depend on this entry; deactivate or merge it instead of deleting it.")
    targets = [
        serialize(candidate, taxonomy_type, db)
        for candidate in db.scalars(select(model_for(taxonomy_type)).where(model_for(taxonomy_type).id != entry_id, model_for(taxonomy_type).is_active.is_(True)).order_by(model_for(taxonomy_type).display_order, model_for(taxonomy_type).name)).all()
    ]
    return TaxonomyImpactResponse(taxonomy_type=taxonomy_type, entry=serialize(item, taxonomy_type, db), dependencies=dependencies, blockers=blockers, merge_targets=targets)


def _reassign_aliases(db: Session, taxonomy_type: str, source, target) -> None:
    source_aliases = list(getattr(source, "aliases", []))
    target_aliases = {alias.normalized_alias for alias in getattr(target, "aliases", [])}
    for alias in source_aliases:
        if alias.normalized_alias in target_aliases:
            raise HTTPException(status_code=409, detail=f"Merge conflict: alias '{alias.alias}' exists on both entries")
    model, owner_key, _ = _alias_model(taxonomy_type)
    db.execute(update(model).where(getattr(model, owner_key) == source.id).values(**{owner_key: target.id}))


def merge_entries(db: Session, taxonomy_type: str, source_id: int, target_id: int, actor: str):
    source = get_entry(db, taxonomy_type, source_id)
    target = get_entry(db, taxonomy_type, target_id)
    if source.id == target.id:
        raise HTTPException(status_code=422, detail="Source and target must be different entries")
    if not source.is_active:
        raise HTTPException(status_code=409, detail="The source entry is already inactive")
    if not target.is_active:
        raise HTTPException(status_code=409, detail="The target entry must be active")
    if taxonomy_type in {"domain", "industry"}:
        validate_parent(db, taxonomy_type, source.id, target.id)
    previous_source = snapshot(source, taxonomy_type, db)
    previous_target = snapshot(target, taxonomy_type, db)
    _reassign_aliases(db, taxonomy_type, source, target)
    if taxonomy_type == "domain":
        db.execute(update(DomainLevelExpectation).where(DomainLevelExpectation.domain_id == source.id).values(domain_id=target.id))
        db.execute(update(DraftExpectation).where(DraftExpectation.domain_id == source.id).values(domain_id=target.id))
        db.execute(update(ResearchFinding).where(ResearchFinding.domain_id == source.id).values(domain_id=target.id))
        for link in list(db.scalars(select(ResearchFindingDomain).where(ResearchFindingDomain.domain_id == source.id)).all()):
            duplicate = db.get(ResearchFindingDomain, {"finding_id": link.finding_id, "domain_id": target.id})
            if duplicate:
                db.delete(link)
            else:
                link.domain_id = target.id
        db.execute(update(SecurityDomain).where(SecurityDomain.parent_id == source.id).values(parent_id=target.id))
    elif taxonomy_type == "industry":
        db.execute(update(DomainLevelExpectation).where(DomainLevelExpectation.industry_id == source.id).values(industry_id=target.id))
        db.execute(update(DraftExpectation).where(DraftExpectation.industry_id == source.id).values(industry_id=target.id))
        db.execute(update(ResearchFinding).where(ResearchFinding.primary_industry_id == source.id).values(primary_industry_id=target.id))
        for link in list(db.scalars(select(ResearchFindingIndustry).where(ResearchFindingIndustry.industry_id == source.id)).all()):
            duplicate = db.get(ResearchFindingIndustry, {"finding_id": link.finding_id, "industry_id": target.id})
            if duplicate:
                db.delete(link)
            else:
                link.industry_id = target.id
        db.execute(update(Industry).where(Industry.parent_id == source.id).values(parent_id=target.id))
    elif taxonomy_type == "career_level":
        db.execute(update(DomainLevelExpectation).where(DomainLevelExpectation.career_level_id == source.id).values(career_level_id=target.id))
        db.execute(update(DraftExpectation).where(DraftExpectation.career_level_id == source.id).values(career_level_id=target.id))
        db.execute(update(ResearchFinding).where(ResearchFinding.career_level_id == source.id).values(career_level_id=target.id))
    else:
        db.execute(update(Competency).where(Competency.category_id == source.id).values(category_id=target.id))
        db.execute(update(ResearchFinding).where(ResearchFinding.category_id == source.id).values(category_id=target.id))
    source.is_active = False
    db.flush()
    db.expire(source, ["aliases"])
    db.expire(target, ["aliases"])
    record_history(db, taxonomy_type, source.id, "merged", previous_source, snapshot(source, taxonomy_type, db), actor, source.id, target.id)
    record_history(db, taxonomy_type, target.id, "merge_target", previous_target, snapshot(target, taxonomy_type, db), actor, source.id, target.id)
    db.commit()
    db.refresh(target)
    return target


def set_active(db: Session, taxonomy_type: str, entry_id: int, active: bool, actor: str):
    item = get_entry(db, taxonomy_type, entry_id)
    previous = snapshot(item, taxonomy_type, db)
    if not active and taxonomy_type in {"domain", "industry"} and getattr(item, "children", []):
        # Deactivation is safe for historical records, but children must remain visible to administrators.
        pass
    item.is_active = active
    db.flush()
    record_history(db, taxonomy_type, item.id, "reactivated" if active else "deactivated", previous, snapshot(item, taxonomy_type, db), actor)
    db.commit()
    db.refresh(item)
    return item


def delete_unused(db: Session, taxonomy_type: str, entry_id: int, actor: str):
    item = get_entry(db, taxonomy_type, entry_id)
    dependencies = dependency_counts(db, taxonomy_type, entry_id)
    if any(dependencies.values()):
        raise HTTPException(status_code=409, detail={"message": "Only unused taxonomy entries can be permanently deleted", "dependencies": dependencies})
    if getattr(item, "children", []):
        raise HTTPException(status_code=409, detail="Move child entries before deleting this taxonomy entry")
    previous = snapshot(item, taxonomy_type, db)
    record_history(db, taxonomy_type, item.id, "deleted", previous, None, actor)
    db.delete(item)
    db.commit()
