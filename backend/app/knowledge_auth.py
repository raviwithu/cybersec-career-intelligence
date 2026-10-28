from __future__ import annotations

import hashlib
import secrets

import redis
from fastapi import Header, HTTPException, status

from .config import get_settings


def _integration_keys() -> set[str]:
    return {item.strip() for item in get_settings().knowledge_integration_keys.split(",") if item.strip()}


def require_proposal_submitter(
    x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
    x_knowledge_integration_key: str | None = Header(default=None, alias="X-Knowledge-Integration-Key"),
) -> str:
    settings = get_settings()
    if settings.admin_api_key and x_admin_api_key and secrets.compare_digest(x_admin_api_key, settings.admin_api_key):
        return "administrator"
    if x_knowledge_integration_key and any(secrets.compare_digest(x_knowledge_integration_key, key) for key in _integration_keys()):
        return f"integration:{hashlib.sha256(x_knowledge_integration_key.encode()).hexdigest()[:24]}"
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="A scoped knowledge proposal credential is required")


def require_knowledge_reviewer(x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key")) -> str:
    from .admin_auth import require_admin

    return require_admin(x_admin_api_key)


def enforce_proposal_rate_limit(actor: str) -> None:
    settings = get_settings()
    try:
        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=0.25, socket_timeout=0.25, decode_responses=True)
        identity = hashlib.sha256(actor.encode()).hexdigest()[:24]
        key = f"knowledge:proposal-rate:{identity}"
        results = client.pipeline().set(key, 0, ex=60, nx=True).incr(key).execute()
        if results[1] > settings.knowledge_proposal_rate_limit_per_minute:
            raise HTTPException(status_code=429, detail="Knowledge proposal rate limit exceeded; retry later")
    except HTTPException:
        raise
    except redis.RedisError:
        # Redis is an optional availability dependency for this write guard. The
        # database and authentication checks remain authoritative if it is down.
        return
