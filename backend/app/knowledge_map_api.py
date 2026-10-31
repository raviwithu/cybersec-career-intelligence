from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from .database import get_db
from .knowledge_map_schemas import MapBranch, MapChildrenResponse, MapPlacement, MapRootResponse, MapSearchResponse, MapTopicChildren, MapTopicPage
from .knowledge_map_service import branch_topics, domain_children, map_etag, map_root, search_topics, topic_children, topic_placements

router = APIRouter(prefix="/knowledge-map", tags=["knowledge-map"])

CACHE_CONTROL = "public, max-age=60"


def _cached(request: Request, response: Response, db: Session, build: Callable[[], Any]) -> Any:
    # Public, published-only data: browsers may reuse it for a minute, then revalidate with If-None-Match.
    etag = map_etag(db)
    headers = {"ETag": etag, "Cache-Control": CACHE_CONTROL}
    if etag in {value.strip() for value in request.headers.get("if-none-match", "").split(",")}:
        return Response(status_code=304, headers=headers)
    payload = build()
    response.headers.update(headers)
    return payload


@router.get("", response_model=MapRootResponse)
def get_map_root(request: Request, response: Response, db: Session = Depends(get_db)):
    return _cached(request, response, db, lambda: map_root(db))


@router.get("/domains/{domain_id}/children", response_model=MapChildrenResponse)
def get_domain_children(domain_id: int, request: Request, response: Response, db: Session = Depends(get_db)):
    return _cached(request, response, db, lambda: domain_children(db, domain_id))


@router.get("/domains/{domain_id}/branches/{branch}/topics", response_model=MapTopicPage)
def get_branch_topics(
    domain_id: int,
    branch: MapBranch,
    request: Request,
    response: Response,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    include_nested: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    return _cached(request, response, db, lambda: branch_topics(db, domain_id, branch, offset, limit, include_nested))


@router.get("/domains/{domain_id}/branches/{branch}/topics/{topic_id}/children", response_model=MapTopicChildren)
def get_topic_children(domain_id: int, branch: MapBranch, topic_id: int, request: Request, response: Response, db: Session = Depends(get_db)):
    return _cached(request, response, db, lambda: topic_children(db, domain_id, branch, topic_id))


@router.get("/topics/{topic_identifier}/placements", response_model=list[MapPlacement])
def get_topic_placements(topic_identifier: str, request: Request, response: Response, db: Session = Depends(get_db)):
    return _cached(request, response, db, lambda: topic_placements(db, topic_identifier))


@router.get("/search", response_model=MapSearchResponse)
def search_map(
    request: Request,
    response: Response,
    q: str = Query(min_length=2, max_length=100),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    return _cached(request, response, db, lambda: search_topics(db, q, limit))
