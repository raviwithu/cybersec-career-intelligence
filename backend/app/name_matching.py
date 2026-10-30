from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Iterable, TypeVar

# Fuzzy matching of skill (competency) and knowledge topic names, so ingestion links research to what already
# exists instead of proposing near-identical new items. Deterministic and explainable: names are reduced to
# significant word stems, then compared by word overlap and character similarity.

STRONG_MATCH = 0.85   # treated as the same item: ingestion links to it automatically
POSSIBLE_MATCH = 0.6  # shown to reviewers as a possible duplicate, never linked automatically

# Words that describe how a skill is phrased in a job ad rather than what the skill is.
FILLER = {
    "a", "an", "and", "the", "of", "for", "in", "on", "to", "with", "within", "across", "using", "via", "by", "or",
    "experience", "experienced", "skill", "skills", "knowledge", "ability", "abilities", "proficiency", "proficient",
    "understanding", "expertise", "familiarity", "strong", "solid", "deep", "hands", "handson", "practical", "working",
    "advanced", "basic", "general", "related", "relevant", "including", "etc", "capability", "capabilities",
    "security", "cyber", "cybersecurity", "information", "infosec",
}
# Abbreviations expanded before comparison.
EXPANSIONS = {
    "dfir": "digital forensics incident response", "ir": "incident response", "iam": "identity access management",
    "appsec": "application", "vuln": "vulnerability", "vulns": "vulnerability", "mgmt": "management",
    "k8s": "kubernetes", "soc": "operations center", "siem": "event management", "grc": "governance risk compliance",
    "ot": "operational technology", "ics": "industrial control systems", "ai": "artificial intelligence", "ml": "machine learning",
    "pentest": "penetration testing", "pentesting": "penetration testing", "devsecops": "devsecops",
}
SUFFIXES = ("ations", "ation", "ships", "ship", "ments", "ment", "ings", "ing", "ers", "er", "ies", "es", "s")

T = TypeVar("T")


def _stem(word: str) -> str:
    # Up to two passes, so "leadership" -> "leader" -> "lead" meets "leading" -> "lead".
    for _ in range(2):
        if len(word) <= 4:
            return word
        for suffix in SUFFIXES:
            if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                word = word[: -len(suffix)] + ("y" if suffix == "ies" else "")
                break
        else:
            return word
    return word


def significant_terms(name: str) -> tuple[str, ...]:
    text = (name or "").casefold().replace("&", " and ").replace("hands-on", "handson")
    words = re.findall(r"[a-z0-9]+", text)
    expanded: list[str] = []
    for word in words:
        expanded.extend(EXPANSIONS.get(word, word).split())
    terms = [_stem(word) for word in expanded if word not in FILLER]
    return tuple(sorted(set(terms)))


def similarity(left: str, right: str) -> float:
    """0..1. Identical significant terms score 1.0; word overlap and character similarity cover rewordings."""
    a, b = significant_terms(left), significant_terms(right)
    if not a or not b:
        return 1.0 if (left or "").strip().casefold() == (right or "").strip().casefold() else 0.0
    if a == b:
        return 1.0
    shared = len(set(a) & set(b))
    jaccard = shared / len(set(a) | set(b))
    characters = SequenceMatcher(None, " ".join(a), " ".join(b)).ratio()
    # One name containing all of the other's terms (e.g. "incident response" in "security incident response handling")
    # is a strong signal only when the shorter name has at least two significant terms.
    containment = shared / min(len(a), len(b)) if min(len(a), len(b)) >= 2 else 0.0
    return round(max(jaccard, 0.5 * jaccard + 0.5 * characters, 0.9 * containment * (0.5 + 0.5 * jaccard)), 3)


def best_match(name: str, candidates: Iterable[T], names_of) -> tuple[T | None, float]:
    """The candidate whose name (or any alias returned by names_of) is most similar to name."""
    best, best_score = None, 0.0
    for candidate in candidates:
        score = max((similarity(name, other) for other in names_of(candidate) if other), default=0.0)
        if score > best_score:
            best, best_score = candidate, score
    return best, best_score
