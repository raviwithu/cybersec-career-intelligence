from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .admin_auth import require_admin
from .database import get_db
from .models import CareerLevel, CompetencyCategory, Industry, SecurityDomain, TaxonomyChangeHistory
from .taxonomy_schemas import TaxonomyCreate, TaxonomyEntryResponse, TaxonomyHistoryPage, TaxonomyHistoryResponse, TaxonomyImpactResponse, TaxonomyManagementResponse, TaxonomyMergeRequest, TaxonomyType, TaxonomyUpdate
from .taxonomy_service import create_entry, delete_unused, get_entry, impact, merge_entries, model_for, serialize, set_active, update_entry

router = APIRouter(prefix="/research/taxonomy", tags=["taxonomy-management"])


@router.get("", response_model=TaxonomyManagementResponse, dependencies=[Depends(require_admin)])
def list_taxonomy(
    taxonomy_type: TaxonomyType | None = None,
    include_inactive: bool = True,
    search: str | None = Query(default=None, max_length=120),
    db: Session = Depends(get_db),
) -> TaxonomyManagementResponse:
    types = [taxonomy_type] if taxonomy_type else ["domain", "industry", "career_level", "category"]
    items = []
    for current_type in types:
        model = model_for(current_type)
        query = select(model)
        if not include_inactive:
            query = query.where(model.is_active.is_(True))
        if search:
            query = query.where(model.name.ilike(f"%{search.strip()}%"))
        options = [selectinload(model.aliases)]
        if current_type in {"domain", "industry"}:
            options.extend([selectinload(model.parent), selectinload(model.children)])
        query = query.options(*options).order_by(model.display_order, model.name)
        items.extend(serialize(item, current_type, db) for item in db.scalars(query).unique().all())
    return TaxonomyManagementResponse(items=[TaxonomyEntryResponse.model_validate(item) for item in items], taxonomy_type=taxonomy_type)


@router.get("/history", response_model=TaxonomyHistoryPage, dependencies=[Depends(require_admin)])
def taxonomy_history(
    taxonomy_type: TaxonomyType | None = None,
    action: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> TaxonomyHistoryPage:
    query = select(TaxonomyChangeHistory)
    if taxonomy_type:
        query = query.where(TaxonomyChangeHistory.taxonomy_type == taxonomy_type)
    if action:
        query = query.where(TaxonomyChangeHistory.action == action)
    total = len(db.scalars(query).all())
    rows = db.scalars(query.order_by(TaxonomyChangeHistory.created_at.desc()).limit(limit)).all()
    return TaxonomyHistoryPage(items=[TaxonomyHistoryResponse.model_validate(row) for row in rows], total=total)


@router.get("/{taxonomy_type}/{entry_id}/impact", response_model=TaxonomyImpactResponse, dependencies=[Depends(require_admin)])
def taxonomy_impact(taxonomy_type: TaxonomyType, entry_id: int, db: Session = Depends(get_db)) -> TaxonomyImpactResponse:
    return impact(db, taxonomy_type, entry_id)


@router.post("/{taxonomy_type}", response_model=TaxonomyEntryResponse, status_code=status.HTTP_201_CREATED)
def create_taxonomy(taxonomy_type: TaxonomyType, payload: TaxonomyCreate, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> TaxonomyEntryResponse:
    item = create_entry(db, taxonomy_type, payload, actor)
    return TaxonomyEntryResponse.model_validate(serialize(item, taxonomy_type, db))


@router.patch("/{taxonomy_type}/{entry_id}", response_model=TaxonomyEntryResponse)
def update_taxonomy(taxonomy_type: TaxonomyType, entry_id: int, payload: TaxonomyUpdate, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> TaxonomyEntryResponse:
    item = update_entry(db, taxonomy_type, entry_id, payload, actor)
    return TaxonomyEntryResponse.model_validate(serialize(item, taxonomy_type, db))


@router.post("/{taxonomy_type}/{entry_id}/merge", response_model=TaxonomyEntryResponse)
def merge_taxonomy(taxonomy_type: TaxonomyType, entry_id: int, payload: TaxonomyMergeRequest, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> TaxonomyEntryResponse:
    item = merge_entries(db, taxonomy_type, entry_id, payload.target_id, actor)
    return TaxonomyEntryResponse.model_validate(serialize(item, taxonomy_type, db))


@router.post("/{taxonomy_type}/{entry_id}/deactivate", response_model=TaxonomyEntryResponse)
def deactivate_taxonomy(taxonomy_type: TaxonomyType, entry_id: int, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> TaxonomyEntryResponse:
    item = set_active(db, taxonomy_type, entry_id, False, actor)
    return TaxonomyEntryResponse.model_validate(serialize(item, taxonomy_type, db))


@router.post("/{taxonomy_type}/{entry_id}/reactivate", response_model=TaxonomyEntryResponse)
def reactivate_taxonomy(taxonomy_type: TaxonomyType, entry_id: int, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> TaxonomyEntryResponse:
    item = set_active(db, taxonomy_type, entry_id, True, actor)
    return TaxonomyEntryResponse.model_validate(serialize(item, taxonomy_type, db))


@router.delete("/{taxonomy_type}/{entry_id}", response_model=None, status_code=status.HTTP_204_NO_CONTENT)
def delete_taxonomy(taxonomy_type: TaxonomyType, entry_id: int, actor: str = Depends(require_admin), db: Session = Depends(get_db)) -> None:
    delete_unused(db, taxonomy_type, entry_id, actor)
