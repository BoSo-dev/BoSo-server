from collections import OrderedDict
from threading import Lock
from time import monotonic
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.core.dependencies import DbSession
from app.core.errors import AppError
from app.modules.auth import security, service
from app.modules.auth.models import User

bearer = HTTPBearer(auto_error=False)


def auth_settings():
    return security.require_auth_settings(get_settings())


AuthSettings = Annotated[Settings, Depends(auth_settings)]


class AuthRateLimiter:
    """Bounded per-process, per-peer admission limit, not a distributed quota.

    Never trust client-supplied Forwarded/X-Forwarded-For here. A deployment
    gateway must also enforce a shared quota across workers/instances.
    """

    def __init__(self):
        self.entries = OrderedDict()
        self.lock = Lock()

    def check(self, peer: str, path: str):
        key = (peer, path)
        now = monotonic()
        with self.lock:
            start, count = self.entries.pop(key, (now, 0))
            if now - start >= 60:
                start, count = now, 0
            self.entries[key] = (start, count + 1)
            while len(self.entries) > 4096:
                self.entries.popitem(last=False)
            if count >= 30:
                raise AppError(429, "AUTH_RATE_LIMITED", "잠시 후 다시 시도해주세요.")


def browser_request(request: Request, settings: AuthSettings):
    origins = request.headers.getlist("origin")
    if len(origins) != 1 or origins[0] not in settings.cors_origins:
        raise AppError(403, "ORIGIN_NOT_ALLOWED", "허용되지 않은 요청 출처입니다.")
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise AppError(415, "JSON_REQUIRED", "JSON 형식으로 요청해주세요.")
    peer = request.client.host if request.client else "unknown"
    request.app.state.auth_rate_limiter.check(peer, request.url.path)


def current_user(
    db: DbSession,
    settings: AuthSettings,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
):
    if credentials is None:
        raise service.unauthorized()
    return service.authenticated_user(db, settings, credentials.credentials)


CurrentUser = Annotated[User, Depends(current_user, scope="function")]
