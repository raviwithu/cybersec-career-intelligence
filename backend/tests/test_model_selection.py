from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import engine
from app.model_selection import EVALUATION_VERSION, ModelSelectionError, ModelSelectionService, score_result
from app.models import ModelEvaluation, ModelSelection
from app.ollama_client import OllamaClient
from app.phase5_schemas import ExtractedRequirement, ExtractionResult


def settings(model="fallback-model"):
    return type("Settings", (), {"ollama_base_url": "http://test", "ollama_model": model, "ollama_timeout_seconds": 1, "ollama_retries": 0})()


def requirement(name, domain, level):
    return ExtractedRequirement(
        competency_name=name, domain_slugs=[domain], career_level=level,
        evidence_excerpt="The posting contains this requirement.", confidence=1,
    )


def test_ollama_discovers_names_and_preserves_api_shape():
    def handler(request):
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "zeta:latest"}, {"model": "alpha:latest"}, {"name": "zeta:latest"}]})
    client = OllamaClient(settings(), httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.list_models() == ["alpha:latest", "zeta:latest"]


def test_fixed_evaluation_scoring_is_deterministic_and_penalizes_hallucinations():
    from app.model_selection import EVALUATION_CASES

    case = EVALUATION_CASES[0]
    result = ExtractionResult(requirements=[
        requirement("API Authorization", "cloud-api-security", "senior"),
        requirement("Unlisted Capability", "cloud-api-security", "senior"),
    ])
    metrics = score_result(result, case)
    assert metrics["extraction_accuracy"] == 1.0
    assert metrics["classification_accuracy"] == 1.0
    assert metrics["hallucination_rate"] == 0.5


class FakeSelectionClient:
    model = "fallback-model"

    def __init__(self, models, failing=None):
        self.models = models
        self.failing = set(failing or [])

    def list_models(self):
        return self.models

    def extract(self, content, taxonomy, model=None):
        if model in self.failing:
            raise RuntimeError("evaluation failure")
        if "cloud APIs" in content:
            return ExtractionResult(requirements=[requirement("API Authorization", "cloud-api-security", "senior")])
        if "Kubernetes" in content:
            return ExtractionResult(requirements=[requirement("Kubernetes Security", "cloud-infrastructure-security", "intermediate")])
        return ExtractionResult(requirements=[requirement("Secure Boot", "boot-security", "architect")])


def test_automatic_selection_chooses_successful_scored_model_and_persists_results():
    service = ModelSelectionService(FakeSelectionClient(["small:latest", "capable:latest"], failing=["small:latest"]), settings())
    with Session(engine) as db:
        evaluations = service.evaluate_and_select(db)
        selection = db.get(ModelSelection, 1)
        assert selection.selected_model == "capable:latest"
        assert selection.mode == "automatic"
        assert selection.evaluation_version == EVALUATION_VERSION
        assert len(evaluations) == 2
        assert db.scalar(select(ModelEvaluation).where(ModelEvaluation.model_name == "capable:latest")) is not None
        db.query(ModelEvaluation).delete()
        db.query(ModelSelection).delete()
        db.commit()


def test_manual_selection_requires_installed_model_and_preserves_fallback_on_total_failure():
    with Session(engine) as db:
        selection = ModelSelection(id=1, selected_model="working:latest", mode="manual", evaluation_version=EVALUATION_VERSION, updated_at=datetime.now(timezone.utc))
        db.add(selection)
        db.commit()
        service = ModelSelectionService(FakeSelectionClient(["broken:latest"], failing=["broken:latest"]), settings())
        with pytest.raises(ModelSelectionError, match="existing model was preserved"):
            service.evaluate_and_select(db)
        assert db.get(ModelSelection, 1).selected_model == "working:latest"
        with pytest.raises(ModelSelectionError, match="not installed"):
            service.set_manual(db, "missing:latest")
        service.set_manual(db, "broken:latest")
        assert db.get(ModelSelection, 1).mode == "manual"
        db.query(ModelEvaluation).delete()
        db.query(ModelSelection).delete()
        db.commit()
