from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai_providers import AIProviderRegistry
from .config import Settings
from .models import ModelEvaluation, ModelSelection
from .ollama_client import OllamaClient, OllamaError
from .phase5_schemas import ExtractionResult
from .provider_common import ProviderError

EVALUATION_VERSION = "cybersec-job-extraction-v1"


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    content: str
    expected_competencies: frozenset[str]
    expected_domains: frozenset[str]
    expected_level: str


EVALUATION_CASES = (
    EvaluationCase(
        "cloud-api-access-control",
        "Senior security engineer: define OAuth2 and JWT authorization for cloud APIs, review privilege boundaries, and lead access-control testing. Requires four years of experience.",
        frozenset({"api-authorization"}), frozenset({"cloud-api-security"}), "senior",
    ),
    EvaluationCase(
        "container-platform-hardening",
        "Security engineer: harden Kubernetes control planes and container images, review deployment paths, and apply threat modeling to cloud infrastructure. Requires independent delivery and two years of experience.",
        frozenset({"kubernetes-security", "container-security", "threat-modeling"}), frozenset({"cloud-infrastructure-security"}), "intermediate",
    ),
    EvaluationCase(
        "embedded-startup-trust",
        "Embedded security architect: design secure boot and chain-of-trust controls, define hardware root-of-trust requirements, and evaluate firmware tampering. Requires eight years of experience.",
        frozenset({"secure-boot", "chain-of-trust", "hardware-root-of-trust"}), frozenset({"boot-security", "embedded-systems-security"}), "architect",
    ),
)

EVALUATION_TAXONOMY = {
    "domains": [
        {"slug": "cloud-api-security", "name": "Cloud API Security"},
        {"slug": "cloud-infrastructure-security", "name": "Cloud Infrastructure Security"},
        {"slug": "embedded-systems-security", "name": "Embedded Systems Security"},
        {"slug": "boot-security", "name": "Boot Security"},
    ],
    "career_levels": [
        {"slug": "intermediate", "name": "Intermediate"},
        {"slug": "senior", "name": "Senior"},
        {"slug": "architect", "name": "Architect"},
    ],
    "categories": [{"slug": "technical-skills", "name": "Technical Skills"}],
    "competencies": [
        {"slug": slug, "name": name, "category_slug": "technical-skills"}
        for slug, name in (
            ("api-authorization", "API Authorization"),
            ("kubernetes-security", "Kubernetes Security"),
            ("container-security", "Container Security"),
            ("threat-modeling", "Threat Modeling"),
            ("secure-boot", "Secure Boot"),
            ("chain-of-trust", "Chain of Trust"),
            ("hardware-root-of-trust", "Hardware Root of Trust"),
        )
    ],
}


class ModelSelectionError(RuntimeError):
    pass


def canonical_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def score_result(result: ExtractionResult, case: EvaluationCase) -> dict[str, float]:
    competency_labels = {canonical_label(requirement.competency_name) for requirement in result.requirements}
    expected_competencies = set(case.expected_competencies)
    extracted_hits = len(competency_labels & expected_competencies)
    extraction_accuracy = extracted_hits / len(expected_competencies)
    hallucination_rate = len(competency_labels - expected_competencies) / max(len(competency_labels), 1)

    domains = {
        canonical_label(value)
        for requirement in result.requirements
        for value in [*requirement.domain_slugs, *requirement.security_subdomains]
    }
    levels = {canonical_label(requirement.career_level or "") for requirement in result.requirements}
    domain_correct = bool(domains & set(case.expected_domains))
    level_correct = case.expected_level in levels
    domain_accuracy = float(domain_correct)
    career_level_accuracy = float(level_correct)
    classification_accuracy = (domain_accuracy + career_level_accuracy) / 2
    return {
        "extraction_accuracy": extraction_accuracy,
        "domain_accuracy": domain_accuracy,
        "career_level_accuracy": career_level_accuracy,
        "classification_accuracy": classification_accuracy,
        "json_validity": 1.0,
        "hallucination_rate": hallucination_rate,
    }


def overall_score(metrics: dict[str, float]) -> float:
    latency_score = max(0.0, min(1.0, 1.0 - metrics["average_processing_ms"] / 10_000.0))
    return round(
        0.40 * metrics["extraction_accuracy"]
        + 0.25 * metrics["classification_accuracy"]
        + 0.20 * metrics["json_validity"]
        + 0.10 * (1.0 - metrics["hallucination_rate"])
        + 0.05 * latency_score,
        4,
    )


def evaluate_model(client: OllamaClient, model_name: str) -> dict[str, Any]:
    totals = {"extraction_accuracy": 0.0, "domain_accuracy": 0.0, "career_level_accuracy": 0.0, "classification_accuracy": 0.0, "json_validity": 0.0, "hallucination_rate": 0.0}
    durations: list[float] = []
    failures: list[str] = []
    for case in EVALUATION_CASES:
        started = time.perf_counter()
        try:
            result = client.extract(case.content, EVALUATION_TAXONOMY, model=model_name)
            metrics = score_result(result, case)
        except Exception as exc:
            metrics = {"extraction_accuracy": 0.0, "domain_accuracy": 0.0, "career_level_accuracy": 0.0, "classification_accuracy": 0.0, "json_validity": 0.0, "hallucination_rate": 1.0}
            failures.append(f"{case.case_id}: {type(exc).__name__}")
        durations.append((time.perf_counter() - started) * 1000)
        for key in totals:
            totals[key] += metrics[key]
    count = len(EVALUATION_CASES)
    metrics = {key: round(value / count, 4) for key, value in totals.items()}
    metrics["average_processing_ms"] = round(sum(durations) / count, 2)
    metrics["overall_score"] = overall_score(metrics)
    metrics["error_message"] = "; ".join(failures) or None
    return metrics


class ModelSelectionService:
    def __init__(self, client: OllamaClient | AIProviderRegistry, settings: Settings):
        self.client = client
        self.settings = settings
        self.providers = client if isinstance(client, AIProviderRegistry) else None

    def catalogs(self):
        if self.providers:
            return self.providers.discover()
        try:
            return [{"provider": "ollama", "models": self.client.list_models(), "status": "connected", "error": None}]
        except OllamaError as exc:
            return [{"provider": "ollama", "models": [], "status": "unavailable", "error": str(exc)}]

    def list_models(self, provider: str = "ollama") -> list[str]:
        if self.providers:
            catalog = next(item for item in self.providers.discover() if item.provider == provider)
            if catalog.status != "connected":
                raise ModelSelectionError(catalog.error or f"{provider} is unavailable")
            return [model.model_id for model in catalog.models]
        try:
            return self.client.list_models()
        except OllamaError as exc:
            raise ModelSelectionError(str(exc)) from exc

    def active_provider(self, db: Session) -> str:
        selection = db.get(ModelSelection, 1)
        return (selection.selected_provider if selection and getattr(selection, "selected_provider", None) else getattr(self.settings, "ai_provider", "ollama"))

    def active_model(self, db: Session) -> str:
        selection = db.get(ModelSelection, 1)
        fallback = getattr(self.settings, "ai_model", None) or self.settings.ollama_model
        return selection.selected_model if selection and selection.selected_model else fallback

    def active_selection(self, db: Session) -> tuple[str, str, str]:
        provider = self.active_provider(db)
        model_id = self.active_model(db)
        return provider, model_id, model_id

    def active_evaluation_version(self, db: Session) -> str:
        selection = db.get(ModelSelection, 1)
        return (selection.evaluation_version if selection and selection.evaluation_version else EVALUATION_VERSION)

    def set_manual(self, db: Session, provider: str = "ollama", model_id: str | None = None, model_name: str | None = None) -> ModelSelection:
        if not self.providers and model_id is None and model_name is None and provider != "ollama":
            model_id, provider = provider, "ollama"
        selected_id = model_id or model_name
        if not selected_id:
            raise ModelSelectionError("A model identifier is required.")
        if self.providers:
            try:
                model = self.providers.model(provider, selected_id)
            except ProviderError as exc:
                raise ModelSelectionError(str(exc)) from exc
            selected_name = model.name
        else:
            installed = self.list_models(provider)
            if selected_id not in installed:
                raise ModelSelectionError("The selected Ollama model is not installed.")
            selected_name = selected_id
        selection = db.get(ModelSelection, 1) or ModelSelection(id=1)
        selection.selected_provider = provider
        selection.selected_model = selected_id
        selection.mode = "manual"
        selection.evaluation_version = EVALUATION_VERSION
        selection.updated_at = datetime.now(timezone.utc)
        db.add(selection)
        db.commit()
        return selection

    def _evaluation_targets(self, provider: str | None = None):
        if self.providers:
            return [(catalog.provider, model.model_id, model.name) for catalog in self.providers.discover() if catalog.status == "connected" and (provider is None or catalog.provider == provider) for model in catalog.models]
        return [("ollama", model, model) for model in self.list_models()]

    def _evaluate_target(self, provider: str, model_id: str) -> dict[str, Any]:
        if self.providers:
            return evaluate_model(self.providers.client(provider), model_id)
        return evaluate_model(self.client, model_id)

    def evaluate_and_select(self, db: Session, provider: str | None = None) -> list[ModelEvaluation]:
        targets = self._evaluation_targets(provider)
        if not targets:
            raise ModelSelectionError("No models are available through configured providers.")
        evaluations: list[ModelEvaluation] = []
        for provider, model_id, model_name in targets:
            metrics = self._evaluate_target(provider, model_id)
            evaluation = ModelEvaluation(
                evaluation_version=EVALUATION_VERSION, provider=provider, model_id=model_id, model_name=model_name,
                extraction_accuracy=metrics["extraction_accuracy"], domain_accuracy=metrics["domain_accuracy"],
                career_level_accuracy=metrics["career_level_accuracy"], classification_accuracy=metrics["classification_accuracy"],
                json_validity=metrics["json_validity"], hallucination_rate=metrics["hallucination_rate"],
                average_processing_ms=metrics["average_processing_ms"], overall_score=metrics["overall_score"],
                error_message=metrics["error_message"], evaluated_at=datetime.now(timezone.utc),
            )
            db.add(evaluation)
            evaluations.append(evaluation)
        successful = [item for item in evaluations if item.error_message is None]
        if not successful:
            db.rollback()
            raise ModelSelectionError("All available models failed evaluation; the existing model was preserved.")
        selected = max(successful, key=lambda item: (item.overall_score, -item.average_processing_ms, item.provider, item.model_id))
        selection = db.get(ModelSelection, 1) or ModelSelection(id=1)
        selection.selected_provider = selected.provider
        selection.selected_model = selected.model_id
        selection.mode = "automatic"
        selection.evaluation_version = EVALUATION_VERSION
        selection.updated_at = datetime.now(timezone.utc)
        db.add(selection)
        db.commit()
        return evaluations

    def recent_evaluations(self, db: Session, provider: str | None = None) -> list[ModelEvaluation]:
        query = select(ModelEvaluation).where(ModelEvaluation.evaluation_version == EVALUATION_VERSION)
        if provider:
            query = query.where(ModelEvaluation.provider == provider)
        return list(db.scalars(query.order_by(ModelEvaluation.overall_score.desc(), ModelEvaluation.evaluated_at.desc())).all())
