"""
Unified Chat API with Agent Integration

Provides a single endpoint for chat interactions with automatic routing.
"""

import asyncio
import uuid
from typing import Any, Dict, List, Optional, AsyncGenerator
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, status
from fastapi.responses import StreamingResponse
from loguru import logger
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from gustobot.application.agents.lg_builder import graph
from gustobot.application.agents.lg_states import InputState, Router
from gustobot.application.agents.utils import message_text
from gustobot.config import settings
from gustobot.config.domain import get_domain_definition
from gustobot.infrastructure.core.database import get_db
from gustobot.infrastructure.persistence.crud import chat_message, chat_session
from gustobot.interfaces.http.models.chat_message import ChatMessageCreate, ChatMessageResponse
from gustobot.interfaces.http.models.chat_session import ChatSessionCreate
from sqlalchemy.orm import Session

router = APIRouter()


class ChatRequest(BaseModel):
    """Chat request model"""

    message: str = Field(..., description="User message", min_length=1, max_length=5000)
    session_id: Optional[str] = Field(None, description="Session ID for conversation continuity")
    user_id: Optional[str] = Field("default_user", description="User identifier")
    stream: bool = Field(False, description="Enable streaming response")
    image_path: Optional[str] = Field(None, description="Path to uploaded image file")
    file_path: Optional[str] = Field(None, description="Path to uploaded file")
    ingest_incremental: Optional[bool] = Field(
        None,
        description=(
            "Override whether Excel ingestion uses incremental mode " "(defaults to server setting)"
        ),
    )


class ChatResponse(BaseModel):
    """Chat response model"""

    message: str
    session_id: str
    message_id: str
    route: Optional[str] = None
    route_logic: Optional[str] = None
    sources: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class ChatStreamChunk(BaseModel):
    """Streaming response chunk"""

    type: str = Field(..., description="Chunk type: 'message', 'metadata', 'error', 'done'")
    content: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None
    route: Optional[str] = None


class ClearSessionResponse(BaseModel):
    message: str
    session_id: str


class RouteDescription(BaseModel):
    name: str
    description: str
    examples: List[str]


class RouteInfoResponse(BaseModel):
    routes: Dict[str, RouteDescription]
    auto_routing: str


def get_or_create_session(db: Session, session_id: Optional[str], user_id: Optional[str]) -> str:
    """Get existing session or create new one"""
    if session_id:
        session = chat_session.get(db, id=session_id)
        if session:
            return session_id

    # Create new session
    new_session_id = str(uuid.uuid4())
    session_data = ChatSessionCreate(
        id=new_session_id,
        user_id=user_id,
        title=f"Chat {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    )
    chat_session.create(db, obj_in=session_data)
    return new_session_id


async def save_message(
    db: Session,
    session_id: str,
    message: str,
    is_user: bool,
    route: Optional[str] = None,
    metadata: Optional[Dict] = None,
):
    """Save message to database"""
    return await run_in_threadpool(_save_message, db, session_id, message, is_user, route, metadata)


def _save_message(
    db: Session,
    session_id: str,
    message: str,
    is_user: bool,
    route: Optional[str],
    metadata: Optional[Dict],
) -> str:
    try:
        last_message = chat_message.get_latest_by_session(db, session_id=session_id)
        next_order_index = (last_message.order_index + 1) if last_message else 1

        message_metadata: Dict[str, Any] = {}
        if metadata is not None:
            # Avoid persisting huge/unstable objects (e.g. full agent graph state).
            message_metadata.update({k: v for k, v in metadata.items() if k != "agent_state"})

        if route:
            message_metadata["route"] = route

        message_data = ChatMessageCreate(
            session_id=session_id,
            message_type="user_query" if is_user else "agent_response",
            content=message,
            message_metadata=message_metadata or None,
            order_index=next_order_index,
        )
        created = chat_message.create(db, obj_in=message_data)

        # Update session activity timestamp so session list ordering stays correct.
        chat_session.update_activity(db, session_id=session_id)
        return str(created.id)
    except Exception:
        try:
            db.rollback()
        except Exception:
            logger.exception("Message save rollback failed while handling the original error")
        raise


async def process_agent_query(
    message: str,
    session_id: str,
    image_path: Optional[str] = None,
    file_path: Optional[str] = None,
    ingest_incremental: Optional[bool] = None,
) -> Dict[str, Any]:
    """Process query through agent system"""
    incremental_flag = (
        settings.INGEST_INCREMENTAL_DEFAULT if ingest_incremental is None else ingest_incremental
    )
    config: RunnableConfig = {
        "configurable": {
            "thread_id": session_id,
            "image_path": image_path,
            "file_path": file_path,
            "incremental": incremental_flag,
        }
    }

    input_state = InputState(messages=[HumanMessage(content=message)])

    try:
        # Invoke agent graph
        result = await graph.ainvoke(input_state, config=config)

        # Extract response and metadata
        response_text = ""
        if result.get("messages"):
            response_text = message_text(result["messages"][-1])

        # Extract route information
        router_info = result.get("router", {})
        if isinstance(router_info, Router):
            router_info = router_info.model_dump()
        route = router_info.get("type")
        route_logic = router_info.get("logic")

        # Extract sources if available
        sources_raw = result.get("sources", [])

        # Convert sources to expected format (list of dicts)
        sources = []
        if sources_raw:
            # If sources is a list of strings, convert to list of dicts
            if isinstance(sources_raw[0], str):
                for src in sources_raw:
                    sources.append({"document_id": src, "source": src})
            else:
                # Already in correct format
                sources = sources_raw

        return {
            "message": response_text,
            "route": route,
            "route_logic": route_logic,
            "sources": sources,
            "metadata": {"session_id": session_id, "agent_state": result},
        }
    except Exception as e:
        logger.exception("Agent query failed")
        return {
            "message": "抱歉，处理您的请求时出现了错误。请稍后重试。",
            "route": "error",
            "route_logic": f"Error: {str(e)}",
            "sources": [],
            "metadata": {"error": str(e)},
        }


async def stream_agent_response(
    message: str,
    session_id: str,
    image_path: Optional[str] = None,
    file_path: Optional[str] = None,
    ingest_incremental: Optional[bool] = None,
) -> AsyncGenerator[str, None]:
    """Stream agent response"""
    # Send initial metadata
    metadata_chunk = ChatStreamChunk(
        type="metadata", metadata={"status": "processing"}, session_id=session_id
    )
    yield f"data: {metadata_chunk.model_dump_json()}\n\n"

    try:
        # Process the query
        result = await process_agent_query(
            message, session_id, image_path, file_path, ingest_incremental
        )

        # Send route information
        route_chunk = ChatStreamChunk(
            type="metadata",
            metadata={"route": result["route"], "logic": result["route_logic"]},
            session_id=session_id,
            route=result["route"],
        )
        yield f"data: {route_chunk.model_dump_json()}\n\n"

        # Stream the response message (simulated - in real implementation, you'd stream from LLM)
        response_text = result["message"]
        words = response_text.split()
        for word in words:
            message_chunk = ChatStreamChunk(
                type="message", content=word + " ", session_id=session_id
            )
            yield f"data: {message_chunk.model_dump_json()}\n\n"
            await asyncio.sleep(0.05)  # Simulate streaming delay

        # Send done signal
        done_chunk = ChatStreamChunk(
            type="done", metadata={"sources": result["sources"]}, session_id=session_id
        )
        yield f"data: {done_chunk.model_dump_json()}\n\n"

    except Exception as e:
        logger.exception("Agent response stream failed")
        error_chunk = ChatStreamChunk(
            type="error", content=f"处理请求时出错: {str(e)}", session_id=session_id
        )
        yield f"data: {error_chunk.model_dump_json()}\n\n"


@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
) -> ChatResponse:
    """
    Unified chat endpoint with automatic agent routing

    - Automatically routes queries to appropriate agents
    - Maintains conversation history
    - Supports file uploads and images
    """
    # Get or create session
    session_id = await run_in_threadpool(
        get_or_create_session, db, request.session_id, request.user_id
    )

    # Save user message
    await save_message(db, session_id, request.message, is_user=True)

    # Process through agent
    result = await process_agent_query(
        request.message,
        session_id,
        request.image_path,
        request.file_path,
        request.ingest_incremental,
    )

    # Save assistant message
    message_id = await save_message(
        db,
        session_id,
        result["message"],
        is_user=False,
        route=result["route"],
        metadata=result["metadata"],
    )

    return ChatResponse(
        message=result["message"],
        session_id=session_id,
        message_id=message_id,
        route=result["route"],
        route_logic=result["route_logic"],
        sources=result["sources"],
        metadata=result["metadata"],
    )


# ---------------------------------------------------------------------------
# Legacy alias routes (backwards compatibility)
#
# Older docs/scripts use `/api/v1/chat/chat` and `/api/v1/chat/chat/stream`.
# Keep them working to reduce migration friction.
# ---------------------------------------------------------------------------


@router.post("/chat", response_model=ChatResponse, include_in_schema=False)
async def chat_legacy(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ChatResponse:
    return await chat(request, background_tasks, db)


@router.post("/stream")
async def chat_stream(request: ChatRequest, db: Session = Depends(get_db)) -> StreamingResponse:
    """
    Streaming chat endpoint with automatic agent routing

    Returns responses in Server-Sent Events (SSE) format
    """
    # Get or create session
    session_id = await run_in_threadpool(
        get_or_create_session, db, request.session_id, request.user_id
    )

    # Save user message
    await save_message(db, session_id, request.message, is_user=True)

    # Return streaming response
    return StreamingResponse(
        stream_agent_response(
            request.message,
            session_id,
            request.image_path,
            request.file_path,
            request.ingest_incremental,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.post("/chat/stream", include_in_schema=False)
async def chat_stream_legacy_post(
    request: ChatRequest,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    return await chat_stream(request, db)


@router.get("/chat/stream", include_in_schema=False)
async def chat_stream_legacy_get(
    message: str = Query(..., min_length=1, max_length=5000),
    session_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query("default_user"),
    image_path: Optional[str] = Query(None),
    file_path: Optional[str] = Query(None),
    ingest_incremental: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    request = ChatRequest(
        message=message,
        session_id=session_id,
        user_id=user_id,
        stream=True,
        image_path=image_path,
        file_path=file_path,
        ingest_incremental=ingest_incremental,
    )
    return await chat_stream(request, db)


@router.get("/history/{session_id}", response_model=List[ChatMessageResponse])
def get_chat_history(
    session_id: str,
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=0, le=100),
    offset: int = Query(0, ge=0),
) -> List[ChatMessageResponse]:
    """
    Get chat history for a session
    """
    # Verify session exists
    session = chat_session.get(db, id=session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    # Get messages
    messages = chat_message.get_by_session(db, session_id=session_id, skip=offset, limit=limit)

    return [ChatMessageResponse.model_validate(message) for message in messages]


@router.delete("/session/{session_id}", response_model=ClearSessionResponse)
def clear_session(session_id: str, db: Session = Depends(get_db)) -> Dict[str, str]:
    """
    Clear all messages in a session
    """
    session = chat_session.get(db, id=session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    # Delete all messages in session
    chat_message.delete_by_session(db, session_id=session_id)

    return {"message": "Session cleared successfully", "session_id": session_id}


@router.get("/routes", response_model=RouteInfoResponse)
async def get_route_info() -> Dict[str, Any]:
    """
    Get information about available routes and their purposes
    """
    domain = get_domain_definition()
    result: Dict[str, Any] = {
        "routes": {
            "general-query": {
                "name": "日常对话",
                "description": "处理问候、寒暄等日常对话",
                "examples": ["你好", "谢谢", "今天天气不错"],
            },
            "additional-query": {
                "name": "补充信息",
                "description": "当问题模糊时，询问更多信息",
                "examples": ["请帮我查一下这个对象"],
            },
            "kb-query": {
                "name": "知识库查询",
                "description": domain.document_scope,
                "examples": ["资料中对这个问题如何说明"],
            },
            "graphrag-query": {
                "name": "图谱查询",
                "description": f"查询{domain.name}中的实体关系",
                "examples": ["这两个对象有什么关联"],
            },
            "text2sql-query": {
                "name": "统计查询",
                "description": "统计分析、计数、排名",
                "examples": ["统计对象数量和排名"],
            },
            "image-query": {
                "name": "图片处理",
                "description": "生成或分析图片",
                "examples": ["生成一张示意图"],
            },
            "file-query": {
                "name": "文件处理",
                "description": "处理上传的领域资料",
                "examples": ["导入这个资料文档"],
            },
        },
        "auto_routing": "系统会根据您的问题自动选择合适的处理方式",
    }
    if not domain.sql_enabled or not settings.SQL_DATABASE_URL:
        del result["routes"]["text2sql-query"]
    return result
