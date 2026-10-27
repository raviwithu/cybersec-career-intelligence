import secrets

from fastapi import Header, HTTPException, status

from .config import get_settings


def require_admin(x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key")) -> str:
    configured_key = get_settings().admin_api_key
    if not configured_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Research administration is disabled until ADMIN_API_KEY is configured")
    if not x_admin_api_key or not secrets.compare_digest(x_admin_api_key, configured_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Valid administrator credentials are required")
    return "administrator"
