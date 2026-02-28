"""Chat request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ChatMessageRequest(BaseModel):
    """POST /v1/chat/message request body."""

    model_config = ConfigDict(from_attributes=True)

    session_id: uuid.UUID
    message: str
    stream: bool = False


class SourceChunk(BaseModel):
    """A source chunk reference returned with a chat response."""

    model_config = ConfigDict(from_attributes=True)

    chunk_id: str
    document: str
    section: str


class ChatMessageResponse(BaseModel):
    """POST /v1/chat/message response body."""

    model_config = ConfigDict(from_attributes=True)

    message_id: uuid.UUID
    response: str
    confidence: float | None = None
    sources: list[SourceChunk] = []
    escalation_required: bool = False
    escalation_reason: str | None = None
    latency_ms: int


class StreamDelta(BaseModel):
    """SSE stream event payload."""

    delta: str = ""
    done: bool = False
    metadata: dict | None = None
