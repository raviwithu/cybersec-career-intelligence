import logging
from typing import Any

import httpx
import redis
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .config import Settings

logger = logging.getLogger("cybersec.health")


def check_database(db: Session) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
        return {"status": "up", "detail": "PostgreSQL connection is available"}
    except SQLAlchemyError:
        logger.exception("database_health_check_failed")
        return {"status": "down", "detail": "Database health check failed"}


def check_redis(settings: Settings) -> dict[str, str]:
    try:
        redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1).ping()
        return {"status": "up", "detail": "Redis connection is available"}
    except redis.RedisError:
        logger.exception("redis_health_check_failed")
        return {"status": "down", "detail": "Redis health check failed"}


def check_ollama(settings: Settings) -> dict[str, str]:
    try:
        response = httpx.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags", timeout=1)
        response.raise_for_status()
        return {"status": "up", "detail": "Host Ollama is reachable"}
    except (httpx.HTTPError, ValueError):
        logger.exception("ollama_health_check_failed")
        return {"status": "down", "detail": "Ollama health check failed"}


def service_status(db: Session, settings: Settings, include_ollama: bool = True) -> dict[str, Any]:
    services = {"postgres": check_database(db), "redis": check_redis(settings)}
    if include_ollama:
        services["ollama"] = check_ollama(settings)
    overall = "healthy" if all(item["status"] == "up" for item in services.values()) else "degraded"
    return {"status": overall, "services": services}
