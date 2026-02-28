"""Qdrant async client wrapper for vector storage and retrieval.

Collection naming convention: f"tenant_{tenant_id}" — enforced here only.
All Qdrant driver errors are caught and re-raised as QdrantConnectionError.
"""

import uuid
from typing import Any

import structlog
from qdrant_client import models as qmodels
from qdrant_client.async_qdrant_client import AsyncQdrantClient

from app.core.config import settings
from app.core.exceptions import QdrantConnectionError

logger = structlog.get_logger(__name__)

_VECTOR_DIM = 3072  # gemini-embedding-001 output dimension
_DISTANCE = qmodels.Distance.COSINE

_client: AsyncQdrantClient = AsyncQdrantClient(
    host=settings.qdrant_host,
    port=settings.qdrant_port,
    api_key=settings.qdrant_api_key or None,
    timeout=10.0,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collection_name(tenant_id: str | uuid.UUID) -> str:
    """Canonical collection name for a tenant. Single source of truth."""
    return f"tenant_{tenant_id}"


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

async def get_qdrant() -> "QdrantService":
    """FastAPI dependency returning the singleton QdrantService wrapper."""
    return QdrantService(_client)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

async def close_qdrant() -> None:
    """Gracefully close the Qdrant connection."""
    logger.info("qdrant_shutdown")
    await _client.close()


# ---------------------------------------------------------------------------
# Service wrapper
# ---------------------------------------------------------------------------

class QdrantService:
    """High-level async wrapper over Qdrant operations.

    Every public method catches qdrant-client exceptions and re-raises
    as QdrantConnectionError for the API layer.
    """

    def __init__(self, client: AsyncQdrantClient) -> None:
        self._q = client

    # -- Collection management -----------------------------------------------

    async def create_collection_if_not_exists(self, tenant_id: str | uuid.UUID) -> str:
        """Ensure a collection exists for the tenant. Returns the collection name.

        Creates with cosine distance and 3072-dim vectors (gemini-embedding-001).
        Idempotent — safe to call on every request.
        """
        name = _collection_name(tenant_id)
        try:
            exists = await self._q.collection_exists(collection_name=name)
            if not exists:
                await self._q.create_collection(
                    collection_name=name,
                    vectors_config=qmodels.VectorParams(
                        size=_VECTOR_DIM,
                        distance=_DISTANCE,
                    ),
                )
                logger.info("qdrant_collection_created", collection=name)
            return name
        except Exception as e:
            logger.error("qdrant_create_collection_failed", collection=name, error=str(e))
            raise QdrantConnectionError(
                f"Failed to create/check Qdrant collection '{name}': {e}"
            ) from e

    async def collection_point_count(self, tenant_id: str | uuid.UUID) -> int:
        """Return the number of points in a tenant's collection. 0 if missing."""
        name = _collection_name(tenant_id)
        try:
            info = await self._q.get_collection(collection_name=name)
            return info.points_count or 0
        except Exception:
            return 0

    # -- Vector operations ---------------------------------------------------

    async def upsert_vectors(
        self,
        tenant_id: str | uuid.UUID,
        points: list[dict[str, Any]],
    ) -> None:
        """Upsert a batch of vectors into the tenant's collection.

        Each point dict must have:
            - "id": str (UUID)
            - "vector": list[float]
            - "payload": dict[str, Any]
        """
        name = _collection_name(tenant_id)
        try:
            qdrant_points = [
                qmodels.PointStruct(
                    id=p["id"],
                    vector=p["vector"],
                    payload=p.get("payload", {}),
                )
                for p in points
            ]
            await self._q.upsert(
                collection_name=name,
                points=qdrant_points,
            )
            logger.debug(
                "qdrant_upsert_ok",
                collection=name,
                point_count=len(qdrant_points),
            )
        except Exception as e:
            logger.error(
                "qdrant_upsert_failed",
                collection=name,
                point_count=len(points),
                error=str(e),
            )
            raise QdrantConnectionError(f"Qdrant upsert failed: {e}") from e

    async def search(
        self,
        tenant_id: str | uuid.UUID,
        query_vector: list[float],
        limit: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Dense vector search in the tenant's collection.

        Returns a list of dicts with keys: id, score, payload.
        Optional filters are translated to Qdrant Filter conditions.
        """
        name = _collection_name(tenant_id)
        query_filter = self._build_filter(filters) if filters else None
        try:
            results = await self._q.search(
                collection_name=name,
                query_vector=query_vector,
                limit=limit,
                query_filter=query_filter,
            )
            hits = [
                {
                    "id": str(r.id),
                    "score": r.score,
                    "payload": r.payload or {},
                }
                for r in results
            ]
            logger.debug(
                "qdrant_search_ok",
                collection=name,
                limit=limit,
                hit_count=len(hits),
            )
            return hits
        except Exception as e:
            logger.error(
                "qdrant_search_failed",
                collection=name,
                error=str(e),
            )
            raise QdrantConnectionError(f"Qdrant search failed: {e}") from e

    async def scroll_all(
        self,
        tenant_id: str | uuid.UUID,
        filters: dict[str, Any] | None = None,
        batch_size: int = 100,
    ) -> list[dict[str, Any]]:
        """Scroll through all points in a tenant's collection.

        Unlike search(), this does not require a query vector and returns
        ALL matching points (paginated internally). Used for BM25 corpus loading.

        Returns a list of dicts with keys: id, payload.
        """
        name = _collection_name(tenant_id)
        query_filter = self._build_filter(filters) if filters else None
        all_points: list[dict[str, Any]] = []
        offset: str | int | None = None

        try:
            while True:
                records, next_offset = await self._q.scroll(
                    collection_name=name,
                    scroll_filter=query_filter,
                    limit=batch_size,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for record in records:
                    all_points.append({
                        "id": str(record.id),
                        "payload": record.payload or {},
                    })
                if next_offset is None:
                    break
                offset = next_offset

            logger.debug(
                "qdrant_scroll_ok",
                collection=name,
                total_points=len(all_points),
            )
            return all_points
        except Exception as e:
            logger.error(
                "qdrant_scroll_failed",
                collection=name,
                error=str(e),
            )
            raise QdrantConnectionError(f"Qdrant scroll failed: {e}") from e

    async def delete_by_filter(
        self,
        tenant_id: str | uuid.UUID,
        filters: dict[str, Any],
    ) -> None:
        """Delete points matching the given filters from the tenant's collection.

        Filters dict maps payload field names to their expected values, e.g.:
            {"document_id": "abc-123"}
        """
        name = _collection_name(tenant_id)
        query_filter = self._build_filter(filters)
        try:
            await self._q.delete(
                collection_name=name,
                points_selector=qmodels.FilterSelector(
                    filter=query_filter,
                ),
            )
            logger.info(
                "qdrant_delete_ok",
                collection=name,
                filters=filters,
            )
        except Exception as e:
            logger.error(
                "qdrant_delete_failed",
                collection=name,
                filters=filters,
                error=str(e),
            )
            raise QdrantConnectionError(f"Qdrant delete failed: {e}") from e

    # -- Internal helpers ----------------------------------------------------

    @staticmethod
    def _build_filter(filters: dict[str, Any]) -> qmodels.Filter:
        """Convert a simple {field: value} dict to a Qdrant Filter with must conditions."""
        must_conditions = [
            qmodels.FieldCondition(
                key=key,
                match=qmodels.MatchValue(value=value),
            )
            for key, value in filters.items()
        ]
        return qmodels.Filter(must=must_conditions)
