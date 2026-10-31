from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

MapBranch = Literal["foundations", "security", "vulnerabilities"]


class MapDomainNode(BaseModel):
    node_type: Literal["domain"] = "domain"
    id: int
    slug: str
    name: str
    child_domain_count: int
    # Distinct published topics placed in this domain or any of its active child domains.
    placed_topic_count: int


class MapBranchNode(BaseModel):
    node_type: Literal["branch"] = "branch"
    domain_id: int
    branch: MapBranch
    label: str
    topic_count: int


class MapRootNode(BaseModel):
    id: Literal["root"] = "root"
    name: str


class MapRootResponse(BaseModel):
    root: MapRootNode
    domains: list[MapDomainNode]


class MapChildrenResponse(BaseModel):
    domain: MapDomainNode
    # Child domains first, then the domain's non-empty branches.
    nodes: list[MapDomainNode | MapBranchNode]


class MapTopicNode(BaseModel):
    id: int
    topic_key: str
    name: str
    short_description: str
    placement_count: int
    has_children: bool
    context_note: str | None = None


class MapTopicPage(BaseModel):
    domain_id: int
    branch: MapBranch
    label: str
    items: list[MapTopicNode]
    total: int
    offset: int
    limit: int


class MapDomainRef(BaseModel):
    id: int
    name: str


class MapTopicRef(BaseModel):
    id: int
    topic_key: str
    name: str


class MapPlacement(BaseModel):
    domain_path: list[MapDomainRef]
    branch: MapBranch
    label: str
    context_note: str | None = None
    ancestors: list[MapTopicRef] = []  # parent topics it is nested under in this branch, outermost first


class MapTopicChildren(BaseModel):
    topic_id: int
    domain_id: int
    branch: MapBranch
    items: list[MapTopicNode]


class MapSearchResult(BaseModel):
    id: int
    topic_key: str
    name: str
    short_description: str
    placements: list[MapPlacement]


class MapSearchResponse(BaseModel):
    query: str
    items: list[MapSearchResult]
