import logging
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.dependencies import DbSession
from app.core.errors import AppError

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


@router.get("/live", response_model=HealthResponse)
def live():
    """Process health; available even before database configuration."""
    return HealthResponse()


@router.get("/ready", response_model=HealthResponse)
def ready(db: DbSession):
    """Readiness checks connectivity. Schema checks are added with domain migrations."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        # Driver exception strings can contain hosts and credentials. Do not log them.
        logger.warning("database_readiness_failed")
        raise AppError(503, "DATABASE_UNAVAILABLE", "데이터베이스에 연결할 수 없습니다.") from None
    return HealthResponse()
