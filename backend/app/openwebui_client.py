from __future__ import annotations

import time
from typing import Any

import httpx
from pydantic import ValidationError

from .config import Settings
from .phase5_schemas import ExtractionResult
from .provider_common import AIModel, ProviderError, SYSTEM_PROMPT, build_extraction_prompt, parse_extraction


class OpenWebUIClient:
    provider = "openwebui"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.base_url = (settings.openwebui_base_url or "").rstrip("/")
        self.api_key = settings.openwebui_api_key
        self.model = settings.ai_model or settings.ollama_model
        self.timeout = settings.openwebui_timeout_seconds or settings.ollama_timeout_seconds
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _ensure_configured(self) -> None:
        if not self.base_url:
            raise ProviderError(self.provider, "OpenWebUI is not configured; set OPENWEBUI_BASE_URL")

    @staticmethod
    def _response_detail(response: httpx.Response) -> str | None:
        try:
            payload = response.json()
        except ValueError:
            return None
        detail = payload.get("detail") or payload.get("error") if isinstance(payload, dict) else None
        if isinstance(detail, dict):
            detail = detail.get("message")
        return " ".join(detail.split())[:200] if isinstance(detail, str) and detail.strip() else None

    def _request_error(self, response: httpx.Response, model_id: str | None = None) -> ProviderError:
        if response.status_code in {401, 403}:
            return ProviderError(self.provider, "OpenWebUI authentication failed; check OPENWEBUI_API_KEY")
        detail = self._response_detail(response)
        if model_id and detail and "model not found" in detail.lower():
            return ProviderError(self.provider, f"Model '{model_id}' is no longer available in OpenWebUI; select another model")
        message = f"OpenWebUI request failed with HTTP {response.status_code}"
        return ProviderError(self.provider, f"{message}: {detail}" if detail else message)

    def list_model_records(self) -> list[AIModel]:
        self._ensure_configured()
        try:
            response = self.client.get(f"{self.base_url}/api/models", headers=self._headers())
            if response.status_code >= 400:
                raise self._request_error(response)
            payload = response.json()
        except ProviderError:
            raise
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise ProviderError(self.provider, "Unable to reach OpenWebUI model listing") from exc

        if isinstance(payload, dict):
            models = payload.get("data", payload.get("models", []))
        else:
            models = payload
        if not isinstance(models, list):
            raise ProviderError(self.provider, "OpenWebUI model listing returned an invalid response")

        records: list[AIModel] = []
        for item in models:
            if not isinstance(item, dict):
                continue
            model_id = item.get("id") or item.get("model") or item.get("name")
            if not isinstance(model_id, str) or not model_id.strip():
                continue
            name = item.get("name") or item.get("title") or item.get("label") or model_id
            provider_info = item.get("owned_by") or item.get("provider") or item.get("source")
            metadata = {
                key: value for key, value in item.items()
                if key not in {"id", "model", "name", "title", "label"}
                and not any(secret in key.lower() for secret in ("api_key", "apikey", "token", "authorization", "password", "secret"))
            }
            records.append(AIModel(
                provider=self.provider,
                model_id=model_id,
                name=name if isinstance(name, str) and name.strip() else model_id,
                provider_info=provider_info if isinstance(provider_info, str) else None,
                metadata=metadata,
            ))
        return sorted({record.model_id: record for record in records}.values(), key=lambda record: record.model_id)

    def list_models(self) -> list[str]:
        return [record.model_id for record in self.list_model_records()]

    def _completion(self, model_id: str, messages: list[dict[str, str]]) -> dict[str, Any]:
        self._ensure_configured()
        if not model_id or len(model_id) > 255:
            raise ProviderError(self.provider, "OpenWebUI model identifier is invalid")
        try:
            response = self.client.post(
                f"{self.base_url}/api/chat/completions",
                headers={**self._headers(), "Content-Type": "application/json"},
                json={"model": model_id, "messages": messages, "stream": False},
            )
            if response.status_code >= 400:
                raise self._request_error(response, model_id)
            payload = response.json()
        except ProviderError:
            raise
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise ProviderError(self.provider, "OpenWebUI chat completion failed") from exc
        if not isinstance(payload, dict):
            raise ProviderError(self.provider, "OpenWebUI returned an invalid chat response")
        return payload

    @staticmethod
    def _content(payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ProviderError("openwebui", "OpenWebUI response did not contain a completion choice")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise ProviderError("openwebui", "OpenWebUI response did not contain a message")
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [item.get("text", "") for item in content if isinstance(item, dict) and isinstance(item.get("text"), str)]
            if parts:
                return "".join(parts)
        raise ProviderError("openwebui", "OpenWebUI response did not contain text content")


    def complete(self, system: str, prompt: str, model: str | None = None) -> str:
        model_id = model or self.model
        return self._content(self._completion(model_id, [{"role": "system", "content": system}, {"role": "user", "content": prompt}])).strip()

    def extract(self, content: str, taxonomy: dict[str, list[dict[str, Any]]], model: str | None = None) -> ExtractionResult:
        model_id = model or self.model
        try:
            raw = self._content(self._completion(model_id, [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_extraction_prompt(content, taxonomy)},
            ]))
            return parse_extraction(raw)
        except ProviderError:
            raise
        except (ValueError, ValidationError) as exc:
            raise ProviderError(self.provider, "OpenWebUI returned malformed extraction JSON") from exc

    def test_model(self, model_id: str) -> float:
        started = time.perf_counter()
        self._content(self._completion(model_id, [
            {"role": "system", "content": "Return a brief connectivity confirmation."},
            {"role": "user", "content": "Connectivity check. Respond with OK."},
        ]))
        return round((time.perf_counter() - started) * 1000, 2)
