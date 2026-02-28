"""Session request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SessionStartRequest(BaseModel):
    """POST /v1/session/start request body."""

    model_config = ConfigDict(from_attributes=True)

    external_user_id: str | None = None


class SessionStartResponse(BaseModel):
    """POST /v1/session/start response body."""

    model_config = ConfigDict(from_attributes=True)

    session_id: uuid.UUID
    created_at: datetime


class SessionEndResponse(BaseModel):
    """POST /v1/session/{session_id}/end response body."""

    model_config = ConfigDict(from_attributes=True)

    session_id: uuid.UUID
    status: str
    summary: dict = {}


class TranscriptMessage(BaseModel):
    """Single message in a transcript."""

    model_config = ConfigDict(from_attributes=True)

    role: str
    content: str
    created_at: datetime
    intent_type: str | None = None
    confidence_score: float | None = None
    escalation_flag: bool = False


class SessionTranscriptResponse(BaseModel):
    """GET /v1/session/{session_id}/transcript response body."""

    model_config = ConfigDict(from_attributes=True)

    session_id: uuid.UUID
    messages: list[TranscriptMessage]
