"""Knowledge ingestion request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class IngestResponse(BaseModel):
    """POST /v1/knowledge/ingest response body."""

    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID
    status: str
    message: str


class DocumentStatusResponse(BaseModel):
    """GET /v1/knowledge/{document_id}/status response body."""

    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID
    status: str
    chunk_count: int | None = None
    error_message: str | None = None


class DocumentListItem(BaseModel):
    """Single document in the list response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    version: int
    status: str
    ingested_at: datetime
    chunk_count: int | None = None


class DocumentListResponse(BaseModel):
    """GET /v1/knowledge/list response body."""

    model_config = ConfigDict(from_attributes=True)

    documents: list[DocumentListItem]


class DocumentDeleteResponse(BaseModel):
    """DELETE /v1/knowledge/{document_id} response body."""

    model_config = ConfigDict(from_attributes=True)

    deleted: bool
