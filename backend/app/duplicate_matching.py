from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Competency, ReviewChange
from .name_matching import POSSIBLE_MATCH, STRONG_MATCH, best_match, similarity

# Matching of newly extracted skills against published competencies and against new skills already waiting in
# Research Review, so repeated ingestion reuses one skill instead of proposing a new one each time.

OPEN_CHANGE_STATUSES = ("pending", "modified", "accepted")
PROMPT_PENDING_SKILLS = 150


def competency_names(competency: Competency) -> list[str]:
    return [competency.name, competency.slug.replace("-", " ")]


def open_new_skill_names(db: Session, limit: int | None = None) -> list[str]:
    """Distinct names of new skills awaiting review, newest first."""
    rows = db.execute(select(ReviewChange.proposed_snapshot).where(ReviewChange.change_type == "new_competency", ReviewChange.status.in_(OPEN_CHANGE_STATUSES)).order_by(ReviewChange.id.desc())).scalars()
    names: list[str] = []
    seen: set[str] = set()
    for snapshot in rows:
        name = ((snapshot or {}).get("competency_name") or "").strip()
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            names.append(name)
            if limit and len(names) >= limit:
                break
    return names


def possible_competency_matches(name: str, competencies: list[Competency], limit: int = 3) -> list[dict[str, Any]]:
    scored = sorted(((max(similarity(name, other) for other in competency_names(item)), item) for item in competencies), key=lambda pair: -pair[0])
    return [{"competency_id": item.id, "name": item.name, "score": score} for score, item in scored[:limit] if POSSIBLE_MATCH <= score < STRONG_MATCH]


def match_skill(name: str, competencies: list[Competency], pending_names: list[str]) -> tuple[Competency | None, str, dict[str, Any] | None]:
    """Returns (existing competency or None, the name to use, how it was matched)."""
    competency, score = best_match(name, competencies, competency_names)
    if competency is not None and score >= STRONG_MATCH:
        return competency, competency.name, {"method": "similar_published_skill", "matched": competency.name, "score": score}
    pending, pending_score = best_match(name, pending_names, lambda value: [value])
    if pending is not None and pending_score >= STRONG_MATCH:
        return None, pending, {"method": "similar_pending_skill", "matched": pending, "score": pending_score} if pending != name else None
    return None, name, None
