"""Shared pytest fixtures for Artrix AI test suite.

Provides:
  - mock_llm: Mock LLMProvider returning configurable responses
  - mock_redis: Mock RedisClient with in-memory dict storage
  - mock_qdrant: Mock QdrantService with call tracking
  - test_db: Async SQLite in-memory session for integration tests
  - sample_tenant: Tenant ORM instance
  - sample_session: Session ORM instance

Heavy third-party SDKs (qdrant_client, cohere, google-generativeai, etc.)
are stubbed in sys.modules below so tests can run without installing them.
All external service calls are mocked in every test — no real SDK usage.
"""

from __future__ import annotations

import importlib
import sys
from types import ModuleType
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Stub heavy third-party SDKs that are NOT needed in test code.
# Must run before any app module imports to prevent ImportError during
# test collection.  Only stubs modules that are missing — already-installed
# packages are left untouched.
# ---------------------------------------------------------------------------

_OPTIONAL_MODULES = [
    # Vector DB
    "qdrant_client",
    "qdrant_client.models",
    "qdrant_client.http",
    "qdrant_client.http.models",
    "qdrant_client.async_qdrant_client",
    # Reranking
    "cohere",
    # Sparse retrieval
    "rank_bm25",
    # LLM SDK
    "google.generativeai",
    "google.generativeai.types",
    "google.ai",
    "google.ai.generativelanguage",
    "openai",
    # Document parsing
    "unstructured",
    "unstructured.partition",
    "unstructured.partition.auto",
    # Postgres driver
    "asyncpg",
    # Redis
    "redis",
    "redis.asyncio",
    "redis.exceptions",
]


def _ensure_module(name: str) -> None:
    """Register a MagicMock stub for *name* only if it cannot be imported."""
    try:
        importlib.import_module(name)
    except (ImportError, ModuleNotFoundError):
        parts = name.split(".")
        # Ensure parent packages exist as stubs too
        for i in range(len(parts)):
            partial = ".".join(parts[: i + 1])
            if partial not in sys.modules:
                stub = ModuleType(partial)
                stub.__dict__.update(
                    {
                        "__path__": [],
                        "__package__": partial,
                    }
                )
                # Make attribute access return MagicMock (mimic SDK classes)
                stub.__class__ = type(
                    "StubModule",
                    (ModuleType,),
                    {"__getattr__": lambda self, attr: MagicMock()},
                )
                sys.modules[partial] = stub


for _mod in _OPTIONAL_MODULES:
    _ensure_module(_mod)

# ---------------------------------------------------------------------------
# Standard test imports (safe now that stubs are in place)
# ---------------------------------------------------------------------------

import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock  # noqa: E402 (reimport intentional)

import pytest

from app.services.llm.base import LLMProvider, LLMResponse


# ---------------------------------------------------------------------------
# Mock LLM Provider
# ---------------------------------------------------------------------------


class MockLLMProvider(LLMProvider):
    """Mock LLM provider for testing. Returns configurable responses."""

    def __init__(
        self,
        generate_text: str = "Mock response",
        embed_vector: list[float] | None = None,
    ) -> None:
        self._generate_text = generate_text
        self._embed_vector = embed_vector or [0.1] * 768
        self.generate_calls: list[dict[str, Any]] = []
        self.embed_calls: list[str] = []
        self.stream_calls: list[dict[str, Any]] = []

    async def generate(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.3,
    ) -> LLMResponse:
        self.generate_calls.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        return LLMResponse(
            text=self._generate_text,
            input_tokens=50,
            output_tokens=10,
        )

    async def stream(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        self.stream_calls.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        for word in self._generate_text.split():
            yield word + " "

    async def embed(self, text: str) -> list[float]:
        self.embed_calls.append(text)
        return list(self._embed_vector)


# ---------------------------------------------------------------------------
# Mock Redis Client
# ---------------------------------------------------------------------------


class MockRedisClient:
    """In-memory mock of RedisClient for testing."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._ttls: dict[str, int] = {}

    async def set_with_ttl(self, key: str, value: str, ttl_seconds: int) -> None:
        self._store[key] = value
        self._ttls[key] = ttl_seconds

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def delete(self, key: str) -> int:
        if key in self._store:
            del self._store[key]
            self._ttls.pop(key, None)
            return 1
        return 0

    async def increment(self, key: str, amount: int = 1) -> int:
        current = int(self._store.get(key, "0"))
        new_val = current + amount
        self._store[key] = str(new_val)
        return new_val

    async def set_json(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        import json

        self._store[key] = json.dumps(value)
        if ttl_seconds:
            self._ttls[key] = ttl_seconds

    async def get_json(self, key: str) -> Any | None:
        import json

        raw = self._store.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def lpush(self, key: str, value: str) -> int:
        import json

        current = json.loads(self._store.get(key, "[]"))
        current.insert(0, value)
        self._store[key] = json.dumps(current)
        return len(current)

    async def lrange(self, key: str, start: int = 0, stop: int = -1) -> list[str]:
        import json

        current = json.loads(self._store.get(key, "[]"))
        if stop == -1:
            return current[start:]
        return current[start : stop + 1]

    async def expire(self, key: str, ttl_seconds: int) -> bool:
        if key in self._store:
            self._ttls[key] = ttl_seconds
            return True
        return False

    @property
    def raw(self) -> Any:
        return MagicMock()


# ---------------------------------------------------------------------------
# Mock Qdrant Service
# ---------------------------------------------------------------------------


class MockQdrantService:
    """Mock QdrantService for testing."""

    def __init__(self) -> None:
        self.collections_created: list[str] = []
        self.upsert_calls: list[dict[str, Any]] = []
        self.search_calls: list[dict[str, Any]] = []
        self.delete_calls: list[dict[str, Any]] = []
        self._search_results: list[dict[str, Any]] = []

    async def create_collection_if_not_exists(self, tenant_id: str) -> None:
        self.collections_created.append(tenant_id)

    async def upsert_vectors(
        self, tenant_id: str, points: list[dict[str, Any]]
    ) -> None:
        self.upsert_calls.append(
            {"tenant_id": tenant_id, "points": points}
        )

    async def search(
        self,
        tenant_id: str,
        query_vector: list[float],
        limit: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.search_calls.append(
            {
                "tenant_id": tenant_id,
                "query_vector": query_vector,
                "limit": limit,
                "filters": filters,
            }
        )
        return self._search_results

    async def scroll_all(
        self,
        tenant_id: str,
        filters: dict[str, Any] | None = None,
        batch_size: int = 100,
    ) -> list[dict[str, Any]]:
        return self._search_results

    async def delete_by_filter(
        self,
        tenant_id: str,
        filters: dict[str, Any],
    ) -> None:
        self.delete_calls.append(
            {"tenant_id": tenant_id, "filters": filters}
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm() -> MockLLMProvider:
    """Mock LLM provider fixture."""
    return MockLLMProvider()


@pytest.fixture
def mock_redis() -> MockRedisClient:
    """Mock Redis client fixture."""
    return MockRedisClient()


@pytest.fixture
def mock_qdrant() -> MockQdrantService:
    """Mock Qdrant service fixture."""
    return MockQdrantService()


@pytest.fixture
def sample_tenant_id() -> uuid.UUID:
    """Fixed tenant UUID for testing."""
    return uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def sample_session_id() -> uuid.UUID:
    """Fixed session UUID for testing."""
    return uuid.UUID("00000000-0000-0000-0000-000000000002")


@pytest.fixture
def sample_tenant_config() -> dict[str, Any]:
    """Sample tenant configuration dict for testing."""
    return {
        "vertical": "ecommerce",
        "persona_name": "TestBot",
        "persona_description": "A test support agent",
        "company_name": "TestCorp",
        "allowed_topics": ["orders", "returns", "shipping"],
        "blocked_topics": ["competitor_comparison"],
        "escalation_threshold": 0.55,
        "auto_resolve_threshold": 0.80,
        "max_turns_before_escalation": 10,
    }


# ---------------------------------------------------------------------------
# Async Database Session (mock — PG-specific types prevent real SQLite)
# ---------------------------------------------------------------------------


@pytest.fixture
def test_db() -> MagicMock:
    """Mock async database session for integration tests.

    The ORM models use PostgreSQL-specific column types (JSONB, ARRAY, UUID)
    which prevent using an in-memory SQLite session. This mock provides the
    full AsyncSession interface needed for unit and integration tests.
    """
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock()
    session.close = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# Sample ORM objects
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_tenant() -> Any:
    """Sample Tenant ORM instance for testing."""
    from app.models.tenant import Tenant

    return Tenant(
        id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        name="Test Corp",
        api_key_hash="sha256_test_hash_value_for_testing",
        vertical="ecommerce",
        is_active=True,
        config={
            "persona_name": "TestBot",
            "persona_description": "A test support agent",
            "company_name": "TestCorp",
            "allowed_topics": ["orders", "returns", "shipping"],
            "blocked_topics": ["competitor_comparison"],
            "escalation_threshold": 0.55,
            "auto_resolve_threshold": 0.80,
            "max_turns_before_escalation": 10,
        },
    )


@pytest.fixture
def sample_session(sample_tenant: Any) -> Any:
    """Sample Session ORM instance for testing."""
    from app.models.session import Session

    return Session(
        id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        tenant_id=sample_tenant.id,
        status="active",
    )


# ---------------------------------------------------------------------------
# Fixture PDF path
# ---------------------------------------------------------------------------


@pytest.fixture
def fixture_pdf_path(tmp_path: Any) -> str:
    """Create a minimal valid PDF for integration tests.

    Returns the file path to a test PDF in a temporary directory.
    Used by test_ingestion.py (parse_document is mocked, but filepath
    must point to a real file per the spec).
    """
    pdf_content = (
        b"%PDF-1.0\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]"
        b"/Parent 2 0 R/Resources<<>>>>endobj\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n206\n%%EOF"
    )
    pdf_path = tmp_path / "test_document.pdf"
    pdf_path.write_bytes(pdf_content)
    return str(pdf_path)
