from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    """聊天请求"""

    message: str = Field(..., description="用户消息", min_length=1)
    session_id: Optional[str] = Field(None, description="会话ID")
    user_id: Optional[str] = Field(None, description="用户ID")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "怎么做红烧肉？",
                "session_id": "session_123",
                "user_id": "user_456",
            }
        }
    )


class ChatResponse(BaseModel):
    """聊天响应"""

    answer: str = Field(..., description="回答")
    session_id: str = Field(..., description="会话ID")
    type: str = Field(..., description="响应类型：knowledge/chat/reject/error")
    metadata: Optional[Dict[str, Any]] = Field(None, description="元数据")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "answer": "红烧肉的做法是...",
                "session_id": "session_123",
                "type": "knowledge",
                "metadata": {
                    "route": "knowledge",
                    "confidence": 0.95,
                },
            }
        }
    )
