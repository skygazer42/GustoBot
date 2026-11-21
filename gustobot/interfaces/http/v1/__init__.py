"""
API v1 router aggregation.

Public chat generation and administrator session management.
"""

from fastapi import APIRouter, Depends

from gustobot.interfaces.http.admin_session import require_admin
from gustobot.interfaces.http.v1 import chat, sessions, upload

api_router = APIRouter()

api_router.include_router(
    sessions.router,
    prefix="/sessions",
    tags=["Chat Sessions"],
    dependencies=[Depends(require_admin)],
)
api_router.include_router(chat.router, prefix="/chat", tags=["Unified Chat"])
api_router.include_router(upload.router, prefix="/upload", tags=["File Upload"])
