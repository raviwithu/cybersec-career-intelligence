from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from .models import DomainLevelExpectation, Industry, IndustryAlias


def normalize_industry(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def industry_query_options():
    return (selectinload(Industry.aliases), selectinload(Industry.parent), selectinload(Industry.children))


def industry_ref(item: Industry | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {"id": item.id, "name": item.name, "slug": item.slug, "description": item.description, "parent_id": item.parent_id, "is_active": item.is_active}


def industry_response(item: Industry) -> dict[str, Any]:
    return {
        **industry_ref(item),
        "aliases": [{"alias": alias.alias, "requires_context": alias.requires_context, "context_hint": alias.context_hint} for alias in item.aliases],
    }


def resolve_industry(db: Session, requested: str, context: str | None = None) -> Industry:
    normalized = normalize_industry(requested)
    item = db.scalar(select(Industry).where(Industry.is_active.is_(True), or_(Industry.slug == normalized.replace(" ", "-"), Industry.name.ilike(requested.strip()))))
    if item is not None:
        return item
    alias = db.scalar(select(IndustryAlias).where(IndustryAlias.normalized_alias == normalized).options(selectinload(IndustryAlias.industry)))
    if alias is None:
        raise HTTPException(status_code=404, detail=f"Industry '{requested}' was not found")
    if alias.requires_context and not context:
        raise HTTPException(status_code=422, detail=f"Industry alias '{requested}' requires context; {alias.context_hint or 'choose a canonical industry'}")
    return alias.industry


def selected_industry_id(db: Session, requested: str | None, context: str | None = None) -> int | None:
    return resolve_industry(db, requested, context).id if requested else None


def expectation_scope_clause(industry_id: int | None):
    if industry_id is None:
        return DomainLevelExpectation.industry_id.is_(None)
    return or_(DomainLevelExpectation.industry_id.is_(None), DomainLevelExpectation.industry_id == industry_id)


def expectation_scope_label(industry: Industry | None) -> str:
    return industry.name if industry is not None else "Cross-industry"


def coverage_query_scope(industry_id: int | None):
    return expectation_scope_clause(industry_id)
