"""Tenant configuration endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant, get_db
from app.models.tenant import Tenant
from app.schemas.config import (
    TenantConfigResponse,
    TenantConfigUpdate,
    TenantConfigUpdateResponse,
)

router = APIRouter(prefix="/config", tags=["config"])


@router.put("", response_model=TenantConfigUpdateResponse)
async def update_config(
    body: TenantConfigUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> TenantConfigUpdateResponse:
    """Update tenant configuration (merge, not overwrite)."""
    current_config = dict(tenant.config) if tenant.config else {}

    # Merge only non-None fields from the request
    update_data = body.model_dump(exclude_none=True)
    current_config.update(update_data)

    tenant.config = current_config
    await db.flush()

    return TenantConfigUpdateResponse(updated=True)


@router.get("", response_model=TenantConfigResponse)
async def get_config(
    tenant: Tenant = Depends(get_current_tenant),
) -> TenantConfigResponse:
    """Get current tenant configuration."""
    return TenantConfigResponse(
        config=dict(tenant.config) if tenant.config else {}
    )
