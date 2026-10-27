import logging
import time
from typing import Any

import httpx
from pydantic import ValidationError

from .config import Settings
from .phase5_schemas import ExtractionResult
from .provider_common import (
    AIModel,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_NO_FORMAT_SUFFIX,
    build_extraction_prompt,
    parse_json,
    supports_json_format,
)

logger = logging.getLogger("cybersec.ollama")

# Kept as a compatibility alias for existing callers.
REASONING_MODEL_PREFIXES = ("gpt-oss",)


class OllamaError(RuntimeError):
    pass


def _supports_json_format(model: str) -> bool:
    return supports_json_format(model)


class OllamaClient:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_model
        self.timeout = settings.ollama_timeout_seconds
        self.retries = max(0, settings.ollama_retries)
        self._client = client

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    def list_model_records(self) -> list[AIModel]:
        try:
            response = self.client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            payload = response.json()
            models = payload.get("models", []) if isinstance(payload, dict) else []
            records = []
            for item in models:
                if not isinstance(item, dict):
                    continue
                model_id = item.get("name") or item.get("model")
                if not isinstance(model_id, str) or not model_id.strip():
                    continue
                details = item.get("details") if isinstance(item.get("details"), dict) else {}
                records.append(AIModel(
                    provider="ollama", model_id=model_id, name=model_id,
                    size=item.get("size") if isinstance(item.get("size"), int) else None,
                    details=details, provider_info="ollama",
                    metadata={key: item[key] for key in ("modified_at", "digest") if key in item},
                ))
            return sorted({record.model_id: record for record in records}.values(), key=lambda record: record.model_id)
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise OllamaError("Unable to discover installed Ollama models") from exc

    def list_models(self) -> list[str]:
        return [record.model_id for record in self.list_model_records()]

    def health(self, model: str | None = None) -> tuple[bool, str]:
        selected_model = model or self.model
        try:
            configured = selected_model in self.list_models()
            return configured, "configured model available" if configured else "configured model is not installed on Ollama"
        except OllamaError as exc:
            logger.warning("ollama_health_failed error_type=%s", type(exc).__name__)
            return False, "Ollama is unavailable"

    def test_model(self, model: str) -> float:
        started = time.perf_counter()
        try:
            response = self.client.post(
                f"{self.base_url}/api/generate",
                json={"model": model, "prompt": "Connectivity check. Respond with OK.", "stream": False, "options": {"temperature": 0}},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("response"), str):
                raise OllamaError("Ollama returned an invalid connectivity response")
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise OllamaError("Ollama model connectivity test failed") from exc
        return round((time.perf_counter() - started) * 1000, 2)

    def extract(self, content: str, taxonomy: dict[str, list[dict[str, Any]]], model: str | None = None) -> ExtractionResult:
        effective_model = model or self.model
        user_prompt = build_extraction_prompt(content, taxonomy)
        payload = {
            "model": effective_model,
            "system": SYSTEM_PROMPT,
            "prompt": user_prompt,
            "stream": False,
            "options": {"temperature": 0},
        }
        if _supports_json_format(effective_model):
            payload["format"] = "json"
        else:
            payload["system"] = SYSTEM_PROMPT + SYSTEM_PROMPT_NO_FORMAT_SUFFIX
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                logger.info("ollama_extraction_started model=%s attempt=%d", effective_model, attempt + 1)
                response = self.client.post(f"{self.base_url}/api/generate", json=payload)
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    raise OllamaError("Ollama response was not an object")
                raw = body.get("response")
                if not isinstance(raw, str):
                    raise OllamaError("Ollama response did not contain a JSON response string")
                parsed = _parse_json(raw)
                result = ExtractionResult.model_validate(parsed)
                logger.info("ollama_extraction_succeeded model=%s requirements=%d", effective_model, len(result.requirements))
                return result
            except (httpx.HTTPError, ValueError, ValidationError, OllamaError) as exc:
                last_error = exc
                logger.warning("ollama_extraction_failed model=%s attempt=%d error_type=%s", effective_model, attempt + 1, type(exc).__name__)
                if attempt < self.retries:
                    time.sleep(min(2 ** attempt, 4))
        raise OllamaError("Ollama extraction failed after configured retries") from last_error


def _parse_json(raw: str) -> dict[str, Any]:
    try:
        return parse_json(raw)
    except Exception as exc:
        if isinstance(exc, OllamaError):
            raise
        raise OllamaError("Ollama returned malformed JSON") from exc
