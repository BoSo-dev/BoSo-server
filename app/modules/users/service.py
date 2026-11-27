from datetime import UTC, date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.modules.auth.models import User
from app.modules.users import repository
from app.modules.users.constants import (
    CARD_LABELS,
    MODE_LABELS,
    REGION_CODES,
    REGION_LABELS,
    TRANSPORT_CARDS,
    TRANSPORT_MODES,
)
from app.modules.users.models import UserProfile
from app.modules.users.schemas import (
    Choice,
    PersonalizationContext,
    ProfileOptions,
    ProfilePatch,
    ProfileResponse,
)


def today_kst():
    return datetime.now(timezone(timedelta(hours=9))).date()


def age_on(birth_date: date | None, reference_date: date):
    if birth_date is None or birth_date > reference_date:
        return None
    return (
        reference_date.year
        - birth_date.year
        - ((reference_date.month, reference_date.day) < (birth_date.month, birth_date.day))
    )


def profile_state(db: Session, user_id: UUID, reference_date: date):
    profile, cards, modes = repository.profile_snapshot(db, user_id)
    birth = profile.birth_date if profile else None
    region = profile.region_code if profile else None
    age = age_on(birth, reference_date)
    missing = []
    for name, value in (
        ("birth_date", birth if age is not None else None),
        ("region_code", region),
        ("transport_cards", cards),
        ("transport_modes", modes),
    ):
        if not value:
            missing.append(name)
    return profile, PersonalizationContext(
        user_id=user_id,
        reference_date=reference_date,
        age=age,
        region_code=region,
        transport_cards=cards,
        transport_modes=modes,
        is_complete=not missing,
        missing_fields=missing,
    )


def read_profile(db: Session, user: User):
    profile, context = profile_state(db, user.id, today_kst())
    return ProfileResponse(
        **context.model_dump(),
        email=user.email,
        birth_date=profile.birth_date if profile else None,
        updated_at=profile.updated_at if profile else None,
    )


def update_profile(db: Session, user: User, patch: ProfilePatch):
    today = today_kst()
    if patch.birth_date is not None and not date(1900, 1, 1) <= patch.birth_date <= today:
        raise AppError(422, "INVALID_BIRTH_DATE", "생년월일을 확인해주세요.")
    if repository.lock_user(db, user.id) is None:
        raise AppError(404, "USER_NOT_FOUND", "사용자를 찾을 수 없습니다.")
    profile = repository.profile_by_user(db, user.id)
    if profile is None:
        profile = UserProfile(user_id=user.id)
        db.add(profile)
        db.flush()
    for name in ("birth_date", "region_code"):
        if name in patch.model_fields_set:
            setattr(profile, name, getattr(patch, name))
    if "transport_cards" in patch.model_fields_set:
        repository.replace_cards(db, user.id, patch.transport_cards)
    if "transport_modes" in patch.model_fields_set:
        repository.replace_modes(db, user.id, patch.transport_modes)
    profile.updated_at = datetime.now(UTC)
    db.flush()
    return read_profile(db, user)


def get_personalization_context(db: Session, user_id: UUID, *, reference_date: date | None = None):
    """Internal service boundary: use an authenticated/authorized ID, never request-supplied ID.

    Deliberately excludes email and full date of birth from downstream context.
    Missing fields and other_or_none must not become an inferred eligibility claim.
    """
    if not repository.active_user_exists(db, user_id):
        raise AppError(404, "USER_NOT_FOUND", "사용자를 찾을 수 없습니다.")
    return profile_state(db, user_id, reference_date or today_kst())[1]


def profile_options():
    def choices(codes, labels):
        return [Choice(code=code, label=label) for code, label in zip(codes, labels, strict=True)]

    return ProfileOptions(
        regions=choices(REGION_CODES, REGION_LABELS),
        transport_cards=choices(TRANSPORT_CARDS, CARD_LABELS),
        transport_modes=choices(TRANSPORT_MODES, MODE_LABELS),
    )
