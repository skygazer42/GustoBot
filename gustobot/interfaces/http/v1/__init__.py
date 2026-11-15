"""
API v1 router aggregation.

Anonymous session management - no authentication required.
"""

from fastapi import APIRouter

from gustobot.interfaces.http.v1 import sessions, chat, upload

api_router = APIRouter()

# Include routers (no authentication required)
api_router.include_router(sessions.router, prefix="/sessions", tags=["Chat Sessions"])
api_router.include_router(chat.router, prefix="/chat", tags=["Unified Chat"])
api_router.include_router(upload.router, prefix="/upload", tags=["File Upload"])
