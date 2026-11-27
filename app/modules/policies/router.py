from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Path, Query

from app.core.dependencies import DbSession
from app.modules.auth.dependencies import CurrentUser
from app.modules.policies import catalog_service as service
from app.modules.policies.schemas import (
    Category,
    PersonalizedPolicyPage,
    PolicyCategory,
    PolicyChanges,
    PolicyDetail,
    PolicyPage,
    PolicySources,
)

router = APIRouter(prefix="/policies", tags=["policies"])

CatalogState = Literal["active", "ended", "expired", "all"]


@router.get("/categories", response_model=list[PolicyCategory])
def categories():
    return service.categories()


@router.get("/for-me", response_model=PersonalizedPolicyPage)
def for_me(
    db: DbSession,
    user: CurrentUser,
    q: str | None = Query(None, min_length=1, max_length=100),
    category: Category | None = None,
    state: CatalogState = "active",
    eligibility: Literal["eligible", "not_eligible", "unknown"] | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1_000_000),
):
    return service.for_user(
        db,
        user.id,
        q=q,
        category=category,
        state=state,
        eligibility=eligibility,
        limit=limit,
        offset=offset,
    )


@router.get("", response_model=PolicyPage)
def list_policies(
    db: DbSession,
    q: str | None = Query(None, min_length=1, max_length=100),
    category: Category | None = None,
    state: CatalogState = "active",
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1_000_000),
):
    return service.list_policies(
        db, q=q, category=category, state=state, limit=limit, offset=offset
    )


@router.get("/{policy_id}", response_model=PolicyDetail)
def read_policy(policy_id: UUID, db: DbSession):
    return service.read_policy(db, policy_id)


@router.get("/{policy_id}/sources", response_model=PolicySources)
def sources(policy_id: UUID, db: DbSession):
    return service.sources(db, policy_id)


@router.get("/{policy_id}/versions", response_model=PolicyPage)
def versions(
    policy_id: UUID,
    db: DbSession,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1_000_000),
):
    return service.history_page(db, policy_id, limit, offset)


@router.get("/{policy_id}/versions/{version}", response_model=PolicyDetail)
def version(policy_id: UUID, db: DbSession, version: int = Path(ge=1)):
    return service.read_policy(db, policy_id, version)


@router.get("/{policy_id}/changes", response_model=PolicyChanges)
def changes(
    policy_id: UUID,
    db: DbSession,
    from_version: int | None = Query(None, ge=1),
    to_version: int | None = Query(None, ge=1),
):
    return service.changes(db, policy_id, from_version, to_version)
