from sqlalchemy import func, or_, select

from app.modules.chat.models import ChatConversation, ChatTurn
from app.modules.policies.models import Policy, PolicyVersion


def conversation(db, owner, conversation_id, *, lock=False):
    statement = select(ChatConversation).where(
        ChatConversation.id == conversation_id, ChatConversation.user_id == owner
    )
    if lock:
        statement = statement.with_for_update()
    return db.scalar(statement)


def conversations(db, owner, limit, offset):
    predicate = ChatConversation.user_id == owner
    total = db.scalar(select(func.count()).select_from(ChatConversation).where(predicate))
    rows = db.scalars(
        select(ChatConversation)
        .where(predicate)
        .order_by(ChatConversation.updated_at.desc(), ChatConversation.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return rows, total


def turn_by_request(db, conversation_id, request_id):
    return db.scalar(
        select(ChatTurn).where(
            ChatTurn.conversation_id == conversation_id, ChatTurn.request_id == request_id
        )
    )


def turns(db, conversation_id, limit, offset=0, *, newest=False):
    statement = select(ChatTurn).where(ChatTurn.conversation_id == conversation_id)
    statement = statement.order_by(ChatTurn.turn_number.desc() if newest else ChatTurn.turn_number)
    return db.scalars(statement.limit(limit).offset(offset)).all()


def turn_count(db, conversation_id):
    return db.scalar(
        select(func.count())
        .select_from(ChatTurn)
        .where(ChatTurn.conversation_id == conversation_id)
    )


def find_policies(db, terms):
    if not terms:
        return []
    predicates = [
        PolicyVersion.title.icontains(term, autoescape=True)
        | PolicyVersion.summary.icontains(term, autoescape=True)
        for term in terms
    ]
    return db.scalars(
        select(Policy.id)
        .join(PolicyVersion, PolicyVersion.policy_id == Policy.id)
        .where(Policy.is_example.is_(False), or_(*predicates))
        .distinct()
        .order_by(Policy.id)
        .limit(5)
    ).all()
