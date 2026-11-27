from sqlalchemy import func, select

from app.modules.auth.models import User
from app.modules.todos.models import UserTodo


def lock_owner(db, user_id):
    return db.scalar(
        select(User.id).where(User.id == user_id, User.is_active.is_(True)).with_for_update()
    )


def owned(db, user_id, todo_id, *, lock=False):
    statement = select(UserTodo).where(UserTodo.id == todo_id, UserTodo.user_id == user_id)
    if lock:
        statement = statement.with_for_update()
    return db.scalar(statement.execution_options(populate_existing=True))


def all_owned(db, user_id):
    return db.scalars(
        select(UserTodo)
        .where(UserTodo.user_id == user_id)
        .execution_options(populate_existing=True)
    ).all()


def page(db, user_id, status, limit, offset):
    predicate = [UserTodo.user_id == user_id]
    if status != "all":
        predicate.append(UserTodo.status == status)
    total = db.scalar(select(func.count()).select_from(UserTodo).where(*predicate))
    rows = db.scalars(
        select(UserTodo)
        .where(*predicate)
        .order_by(UserTodo.created_at.desc(), UserTodo.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return rows, total
