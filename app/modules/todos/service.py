from datetime import UTC, datetime

from sqlalchemy import func, select

from app.core.errors import AppError
from app.modules.policies.models import Policy
from app.modules.policies.service import get_policy_context, today_kst
from app.modules.todos import repository
from app.modules.todos.eligibility import evaluate_eligibility
from app.modules.todos.models import UserTodo
from app.modules.todos.schemas import (
    EligibilityResult,
    PolicyAssessment,
    TodoItem,
    TodoPage,
    TodoSummary,
    TodoSyncResult,
)
from app.modules.users.service import get_personalization_context


def lock_todo_owner(db, user_id):
    if repository.lock_owner(db, user_id) is None:
        raise AppError(404, "USER_NOT_FOUND", "사용자를 찾을 수 없습니다.")


def item(row, today=None):
    today = today or today_kst()
    return TodoItem(
        **{
            field: getattr(row, field)
            for field in TodoItem.model_fields
            if field not in {"policy_version_id", "is_overdue"}
        },
        policy_version_id=row.action.version_id,
        is_overdue=row.status == "pending" and row.due_date is not None and row.due_date < today,
    )


def read_todo(db, user_id, todo_id):
    row = repository.owned(db, user_id, todo_id)
    if row is None:
        raise AppError(404, "TODO_NOT_FOUND", "할 일을 찾을 수 없습니다.")
    return item(row)


def list_todos(db, user_id, status="pending", limit=20, offset=0):
    rows, total = repository.page(db, user_id, status, limit, offset)
    return TodoPage(items=[item(row) for row in rows], total=total, limit=limit, offset=offset)


def summary(db, user_id):
    today = today_kst()
    values = db.execute(
        select(
            func.count().filter(UserTodo.status == "pending"),
            func.count().filter(UserTodo.status == "completed"),
            func.count().filter(UserTodo.status == "archived"),
            func.count().filter((UserTodo.status == "pending") & (UserTodo.due_date < today)),
        ).where(UserTodo.user_id == user_id)
    ).one()
    return TodoSummary(**dict(zip(TodoSummary.model_fields, values, strict=True)))


def synchronize(db, user_id, *, reference_date=None):
    lock_todo_owner(db, user_id)
    today = reference_date or today_kst()
    profile = get_personalization_context(db, user_id, reference_date=today)
    existing = {(row.policy_id, row.action_key): row for row in repository.all_owned(db, user_id)}
    current, reasons, assessments = {}, {}, []
    for policy_id in db.scalars(
        select(Policy.id).where(Policy.is_example.is_(False)).order_by(Policy.id)
    ):
        try:
            context = get_policy_context(db, policy_id, today)
        except AppError as exc:
            if exc.code == "POLICY_NOT_EFFECTIVE":
                reasons[policy_id] = "policy_inactive"
                continue
            raise
        result = (
            evaluate_eligibility(context.eligibility, profile)
            if context.state == "active"
            else EligibilityResult(state="not_eligible", reasons=["policy_inactive"])
        )
        assessments.append(PolicyAssessment(policy_id=policy_id, result=result))
        if context.state != "active":
            reasons[policy_id] = "policy_inactive"
        elif result.state != "eligible":
            reasons[policy_id] = (
                "eligibility_unknown" if result.state == "unknown" else "not_eligible"
            )
        else:
            for action in context.actions:
                current[(policy_id, action.action_key)] = action
    counts = {"created": 0, "updated": 0, "archived": 0}
    for key, action in current.items():
        row = existing.get(key)
        if row is not None and row.status == "completed":
            continue
        values = dict(
            action_id=action.id,
            title=action.title,
            description=action.description,
            due_date=action.due_date,
            status="pending",
            archived_reason=None,
        )
        if row is None:
            row = UserTodo(user_id=user_id, policy_id=key[0], action_key=key[1], **values)
            db.add(row)
            counts["created"] += 1
        elif any(getattr(row, name) != value for name, value in values.items()):
            for name, value in values.items():
                setattr(row, name, value)
            row.updated_at = datetime.now(UTC)
            counts["updated"] += 1
    for key, row in existing.items():
        if key not in current and row.status == "pending":
            row.status = "archived"
            row.archived_reason = reasons.get(row.policy_id, "action_removed")
            row.updated_at = datetime.now(UTC)
            counts["archived"] += 1
    db.flush()
    return TodoSyncResult(**counts, assessments=assessments)


def change_completion(db, user_id, todo_id, completed):
    lock_todo_owner(db, user_id)
    row = repository.owned(db, user_id, todo_id, lock=True)
    if row is None:
        raise AppError(404, "TODO_NOT_FOUND", "할 일을 찾을 수 없습니다.")
    if completed and row.status == "completed":
        return item(row)
    today = today_kst()
    context = get_policy_context(db, row.policy_id, today)
    profile = get_personalization_context(db, user_id, reference_date=today)
    eligible = evaluate_eligibility(context.eligibility, profile).state == "eligible"
    current_action = next(
        (action for action in context.actions if action.action_key == row.action_key), None
    )
    if (
        row.status == "archived"
        or context.state != "active"
        or not eligible
        or current_action is None
    ):
        raise AppError(409, "TODO_NOT_ACTIVE", "정책과 대상 조건을 다시 확인해주세요.")
    row.status = "completed" if completed else "pending"
    row.action_id = current_action.id
    row.title = current_action.title
    row.description = current_action.description
    row.due_date = current_action.due_date
    row.completed_at = datetime.now(UTC) if completed else None
    row.updated_at = datetime.now(UTC)
    db.flush()
    db.expire(row, ["action"])
    return item(row)


def related_todos(db, user_id, policy_ids):
    if not policy_ids:
        return []
    rows = db.scalars(
        select(UserTodo)
        .where(
            UserTodo.user_id == user_id,
            UserTodo.policy_id.in_(policy_ids),
            UserTodo.status != "archived",
        )
        .order_by(UserTodo.created_at, UserTodo.id)
        .limit(100)
    ).all()
    return [item(row) for row in rows]


def pending_todos(db, user_id):
    """Internal callers must authorize and lock the owner before scheduling."""
    return db.scalars(
        select(UserTodo)
        .where(UserTodo.user_id == user_id, UserTodo.status == "pending")
        .order_by(UserTodo.id)
    ).all()
