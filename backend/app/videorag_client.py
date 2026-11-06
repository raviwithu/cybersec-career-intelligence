from __future__ import annotations

from typing import Any

import httpx

from .config import Settings
from .provider_common import ProviderError


class VideoRagClient:
    """The private VideoRAG knowledge DB. Its sources are private course material, so nothing from it reaches a remote model, except the short drafts an administrator chooses to have Kimi check."""

    provider = "videorag"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.base_url = (settings.videorag_base_url or "").rstrip("/")
        self.access_key = settings.videorag_access_key
        self.timeout = settings.videorag_timeout_seconds
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.access_key)

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def _request(self, method: str, path: str, timeout: float | None = None, **kwargs: Any) -> Any:
        if not self.configured:
            raise ProviderError(self.provider, "The RAG knowledge DB is not configured; set VIDEORAG_BASE_URL and VIDEORAG_ACCESS_KEY")
        try:
            response = self.client.request(method, f"{self.base_url}{path}", headers={"Authorization": f"Bearer {self.access_key}"}, timeout=timeout or self.timeout, **kwargs)
        except httpx.TimeoutException as exc:
            raise ProviderError(self.provider, "The RAG knowledge DB timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(self.provider, "The RAG knowledge DB could not be reached") from exc
        if response.status_code in {401, 403}:
            raise ProviderError(self.provider, "The RAG knowledge DB refused the request; check VIDEORAG_ACCESS_KEY")
        if response.status_code >= 400:
            raise ProviderError(self.provider, f"The RAG knowledge DB returned HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError(self.provider, "The RAG knowledge DB returned an unreadable response") from exc

    def coverage(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/api/v1/coverage", timeout=10)
        return data if isinstance(data, list) else []

    def ask(self, question: str, domain: str | None = None) -> dict[str, Any]:
        """With no domain, the service searches everything it has indexed."""
        data = self._request("POST", "/api/v1/ask", json={"q": question, **({"domain": domain} if domain else {})})
        if not isinstance(data, dict):
            raise ProviderError(self.provider, "The RAG knowledge DB returned an unreadable response")
        return data
