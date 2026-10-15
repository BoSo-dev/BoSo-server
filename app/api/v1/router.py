from fastapi import APIRouter

from app.modules.auth.router import router as auth_router
from app.modules.chat.router import router as chat_router
from app.modules.notifications.router import router as notifications_router
from app.modules.policies.router import router as policies_router
from app.modules.todos.router import router as todos_router
from app.modules.users.router import router as users_router

router = APIRouter(prefix="/api/v1")
router.include_router(auth_router)
router.include_router(users_router)
router.include_router(policies_router)
router.include_router(todos_router)
router.include_router(chat_router)
router.include_router(notifications_router)
