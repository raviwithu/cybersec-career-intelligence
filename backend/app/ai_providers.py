from __future__ import annotations

import re
import time
from dataclasses import replace
from typing import Any

from .config import Settings
from .ollama_client import OllamaClient, OllamaError
from .openwebui_client import OpenWebUIClient
from .phase5_schemas import ExtractionResult
from .provider_common import AIModel, ProviderCatalog, ProviderError

PROVIDERS = ("ollama", "openwebui")


def _duplicate_key(model: AIModel) -> str:
    value = model.model_id.casefold().strip()
    return re.sub(r"[^a-z0-9]+", "", value)


class AIProviderRegistry:
    def __init__(self, settings: Settings, ollama: OllamaClient | None = None, openwebui: OpenWebUIClient | None = None):
        self.settings = settings
        self.ollama = ollama or OllamaClient(settings)
        self.openwebui = openwebui or OpenWebUIClient(settings)
        self.clients = {"ollama": self.ollama, "openwebui": self.openwebui}

    def client(self, provider: str):
        try:
            return self.clients[provider]
        except KeyError as exc:
            raise ProviderError(provider, f"Unsupported AI provider: {provider}") from exc

    def _catalog(self, provider: str) -> ProviderCatalog:
        client = self.client(provider)
        if provider == "openwebui" and not client.configured:
            return ProviderCatalog(provider=provider, status="unconfigured", error="OpenWebUI is not configured; set OPENWEBUI_BASE_URL")
        try:
            models = tuple(client.list_model_records())
            return ProviderCatalog(provider=provider, status="connected", models=models)
        except (OllamaError, ProviderError) as exc:
            return ProviderCatalog(provider=provider, status="unavailable", error=str(exc))

    def discover(self) -> list[ProviderCatalog]:
        catalogs = [self._catalog(provider) for provider in PROVIDERS]
        grouped: dict[str, list[tuple[int, AIModel]]] = {}
        for index, catalog in enumerate(catalogs):
            for model in catalog.models:
                grouped.setdefault(_duplicate_key(model), []).append((index, model))
        for key, matches in grouped.items():
            if len(matches) < 2:
                continue
            routes = tuple(f"{model.provider}:{model.model_id}" for _, model in matches)
            for index, model in matches:
                updated = replace(model, possible_duplicate=True, duplicate_with=tuple(route for route in routes if route != f"{model.provider}:{model.model_id}"))
                models = list(catalogs[index].models)
                models[models.index(model)] = updated
                catalogs[index] = replace(catalogs[index], models=tuple(models))
        return catalogs

    def model(self, provider: str, model_id: str) -> AIModel:
        catalog = next(item for item in self.discover() if item.provider == provider)
        for model in catalog.models:
            if model.model_id == model_id:
                return model
        if catalog.status != "connected":
            raise ProviderError(provider, catalog.error or f"{provider} is unavailable")
        raise ProviderError(provider, f"Model '{model_id}' is not currently available through {provider}")

    @staticmethod
    def _validate_model_id(model_id: str) -> None:
        if not isinstance(model_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,254}", model_id):
            raise ProviderError("provider", "Model identifier is invalid")

    def extract_selected(self, provider: str, model_id: str, content: str, taxonomy: dict[str, list[dict[str, Any]]]) -> ExtractionResult:
        self._validate_model_id(model_id)
        client = self.client(provider)
        if provider == "ollama" and model_id == client.model:
            return client.extract(content, taxonomy)
        return client.extract(content, taxonomy, model=model_id)


    def complete_selected(self, provider: str, model_id: str, system: str, prompt: str) -> str:
        self._validate_model_id(model_id)
        client = self.client(provider)
        return client.complete(system, prompt, model=model_id)

    def test_model(self, provider: str, model_id: str) -> float:
        self._validate_model_id(model_id)
        return self.client(provider).test_model(model_id)

    def close(self) -> None:
        self.ollama.close()
        self.openwebui.close()
