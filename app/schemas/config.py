"""Tenant configuration request/response schemas."""

from typing import Any

from pydantic import BaseModel, ConfigDict


class TenantConfigUpdate(BaseModel):
    """PUT /v1/config request body."""

    model_config = ConfigDict(from_attributes=True)

    persona_name: str | None = None
    persona_description: str | None = None
    escalation_webhook_url: str | None = None
    escalation_threshold: float | None = None
    auto_resolve_threshold: float | None = None
    max_turns_before_escalation: int | None = None
    allowed_topics: list[str] | None = None
    blocked_topics: list[str] | None = None
    data_webhook_url: str | None = None
    company_name: str | None = None


class TenantConfigUpdateResponse(BaseModel):
    """PUT /v1/config response body."""

    model_config = ConfigDict(from_attributes=True)

    updated: bool


class TenantConfigResponse(BaseModel):
    """GET /v1/config response body."""

    model_config = ConfigDict(from_attributes=True)

    config: dict[str, Any]
