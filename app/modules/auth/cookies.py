from datetime import datetime

from fastapi import Response

from app.core.config import Settings
from app.modules.auth import security


def cookie_names(settings: Settings):
    prefix = "__Host-boso" if settings.app_env == "production" else "boso-dev"
    return f"{prefix}-refresh", f"{prefix}-csrf"


def set_cookies(
    response: Response, settings: Settings, refresh: str | None, csrf: str, expiry: datetime
):
    refresh_name, csrf_name = cookie_names(settings)
    options = {
        "secure": settings.app_env == "production",
        "samesite": "lax",
        "path": "/",
        "max_age": max(0, int((security.as_utc(expiry) - security.now_utc()).total_seconds())),
    }
    if refresh is not None:
        response.set_cookie(refresh_name, refresh, httponly=True, **options)
    response.set_cookie(csrf_name, csrf, httponly=False, **options)


def clear_cookies(response: Response, settings: Settings):
    refresh_name, csrf_name = cookie_names(settings)
    for name in (refresh_name, csrf_name):
        response.delete_cookie(
            name,
            path="/",
            secure=settings.app_env == "production",
            httponly=name == refresh_name,
            samesite="lax",
        )
