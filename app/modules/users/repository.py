from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.modules.auth.models import User
from app.modules.users.models import UserProfile, UserTransportCard, UserTransportMode


def active_user_exists(db: Session, user_id: UUID):
    return (
        db.scalar(select(User.id).where(User.id == user_id, User.is_active.is_(True))) is not None
    )


def lock_user(db: Session, user_id: UUID):
    # Serializes the first profile insert and concurrent child-list replacement.
    return db.scalar(select(User.id).where(User.id == user_id).with_for_update())


def profile_by_user(db: Session, user_id: UUID):
    return db.get(UserProfile, user_id, populate_existing=True)


def profile_snapshot(db: Session, user_id: UUID):
    # One statement gives a single READ COMMITTED snapshot across all three
    # tables. Separate SELECTs could combine old profile fields with new lists.
    # The code CHECKs and composite PKs bound the join to at most 3 * 2 rows.
    rows = db.execute(
        select(UserProfile, UserTransportCard.card_code, UserTransportMode.mode_code)
        .select_from(UserProfile)
        .outerjoin(UserTransportCard, UserTransportCard.user_id == UserProfile.user_id)
        .outerjoin(UserTransportMode, UserTransportMode.user_id == UserProfile.user_id)
        .where(UserProfile.user_id == user_id)
        .execution_options(populate_existing=True)
    ).all()
    if not rows:
        return None, [], []
    cards = sorted({card for _, card, _ in rows if card is not None})
    modes = sorted({mode for _, _, mode in rows if mode is not None})
    return rows[0][0], cards, modes


def replace_cards(db: Session, user_id: UUID, codes: list[str]):
    db.execute(delete(UserTransportCard).where(UserTransportCard.user_id == user_id))
    db.add_all(UserTransportCard(user_id=user_id, card_code=code) for code in codes)


def replace_modes(db: Session, user_id: UUID, codes: list[str]):
    db.execute(delete(UserTransportMode).where(UserTransportMode.user_id == user_id))
    db.add_all(UserTransportMode(user_id=user_id, mode_code=code) for code in codes)
