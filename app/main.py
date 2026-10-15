import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.errors import install_error_handlers

logger = logging.getLogger("boso.http")


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="BoSo API",
        version="0.1.0",
        description="BoSo 회원 및 교통 정책 API. 현재 브랜치는 프로젝트 기반을 제공합니다.",
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.app_env != "production" else None,
    )
    install_error_handlers(application)
    application.include_router(health_router)

    @application.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid4())
        started = perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Do not log exception messages or request bodies containing secrets.
            logger.error("unhandled_request_error request_id=%s", request.state.request_id)
            response = JSONResponse(
                status_code=500,
                content={
                    "code": "INTERNAL_ERROR",
                    "message": "서버 오류가 발생했습니다.",
                    "details": None,
                    "request_id": request.state.request_id,
                },
            )
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        route = request.scope.get("route")
        logger.info(
            "request method=%s route=%s status=%s duration_ms=%.1f request_id=%s",
            request.method,
            getattr(route, "path", "unmatched"),
            response.status_code,
            (perf_counter() - started) * 1000,
            request.state.request_id,
        )
        return response

    # CORS wraps error responses too.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["X-Request-ID"],
    )
    return application


app = create_app()
