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


class MapRootNode(BaseModel):
    id: Literal["root"] = "root"
    name: str


class MapRootResponse(BaseModel):
    root: MapRootNode
    domains: list[MapDomainNode]


class MapTopicNode(BaseModel):
    id: int
    topic_key: str
    name: str
    short_description: str
    placement_count: int
    has_children: bool  # whether any topic sits in one of its branches in this domain
    context_note: str | None = None


class MapDomainTopicNode(MapTopicNode):
    node_type: Literal["topic"] = "topic"
    domain_id: int


class MapChildrenResponse(BaseModel):
    domain: MapDomainNode
    # Child domains first, then the topics placed directly in the domain. Branches belong to topics.
    nodes: list[MapDomainNode | MapDomainTopicNode]


class MapTopicBranch(BaseModel):
    branch: MapBranch
    label: str
    topic_count: int
    items: list[MapTopicNode]


class MapDomainRef(BaseModel):
    id: int
    name: str


class MapTopicRef(BaseModel):
    id: int
    topic_key: str
    name: str
    branch: MapBranch | None  # the branch of its own parent it sits in; None for the outermost, which sits under the domain


class MapPlacement(BaseModel):
    domain_path: list[MapDomainRef]
    branch: MapBranch | None  # the branch of its parent topic it sits in; None when it sits directly under the domain
    label: str | None
    context_note: str | None = None
    ancestors: list[MapTopicRef] = []  # parent topics it sits under in this domain, outermost first


class MapTopicChildren(BaseModel):
    topic_id: int
    domain_id: int
    # All three in Foundations, Security, Common Vulnerabilities order. A topic inside Common Vulnerabilities has none,
    # apart from any that already hold topics.
    branches: list[MapTopicBranch]
    # What the topic's section nodes can open, in display order. Empty: the topic has no section nodes.
    sections: list[str] = []


class MapSearchResult(BaseModel):
    id: int
    topic_key: str
    name: str
    short_description: str
    placements: list[MapPlacement]


class MapSearchResponse(BaseModel):
    query: str
    items: list[MapSearchResult]
