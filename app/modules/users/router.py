from fastapi import APIRouter

from app.core.dependencies import DbSession
from app.modules.auth.dependencies import CurrentUser
from app.modules.users import service
from app.modules.users.schemas import ProfileOptions, ProfilePatch, ProfileResponse

router = APIRouter(prefix="/me", tags=["users"])


@router.get("", response_model=ProfileResponse)
def get_profile(user: CurrentUser, db: DbSession):
    return service.read_profile(db, user)


@router.patch("", response_model=ProfileResponse)
def patch_profile(body: ProfilePatch, user: CurrentUser, db: DbSession):
    return service.update_profile(db, user, body)


@router.get("/options", response_model=ProfileOptions)
def get_profile_options(user: CurrentUser):
    return service.profile_options()
