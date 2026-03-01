"""Tenant ORM model."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.postgres import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    domain_whitelist: Mapped[list[str] | None] = mapped_column(
        ARRAY(String), nullable=True
    )
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    vertical: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # 'ecommerce' | 'healthcare' | 'bfsi'
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships — lazy="noload" to avoid loading all rows on every request.
    # Use explicit eager loading only when needed (e.g., admin dashboards).
    sessions: Mapped[list["Session"]] = relationship(  # noqa: F821
        back_populates="tenant", lazy="noload"
    )
    messages: Mapped[list["Message"]] = relationship(  # noqa: F821
        back_populates="tenant", lazy="noload"
    )
    billing_events: Mapped[list["BillingEvent"]] = relationship(  # noqa: F821
        back_populates="tenant", lazy="noload"
    )
    knowledge_documents: Mapped[list["KnowledgeDocument"]] = relationship(  # noqa: F821
        back_populates="tenant", lazy="noload"
    )
