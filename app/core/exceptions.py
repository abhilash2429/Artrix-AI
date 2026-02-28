"""Custom exception classes for structured error handling."""

from typing import Any


class ArtrixError(Exception):
    """Base exception for all Artrix errors."""

    def __init__(self, code: str, message: str, status_code: int = 500) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message}}


class InvalidSessionError(ArtrixError):
    def __init__(self, message: str = "Session not found or expired") -> None:
        super().__init__(code="INVALID_SESSION", message=message, status_code=404)


class SessionInactiveError(ArtrixError):
    def __init__(self, message: str = "Session is not active") -> None:
        super().__init__(code="SESSION_INACTIVE", message=message, status_code=409)


class InvalidAPIKeyError(ArtrixError):
    def __init__(self, message: str = "Invalid or missing API key") -> None:
        super().__init__(code="INVALID_API_KEY", message=message, status_code=401)


class TenantNotFoundError(ArtrixError):
    def __init__(self, message: str = "Tenant not found") -> None:
        super().__init__(code="TENANT_NOT_FOUND", message=message, status_code=404)


class TenantInactiveError(ArtrixError):
    def __init__(self, message: str = "Tenant account is inactive") -> None:
        super().__init__(code="TENANT_INACTIVE", message=message, status_code=401)


class RateLimitExceededError(ArtrixError):
    def __init__(self, message: str = "Rate limit exceeded") -> None:
        super().__init__(code="RATE_LIMIT_EXCEEDED", message=message, status_code=429)


class IngestionError(ArtrixError):
    def __init__(self, message: str = "Document ingestion failed") -> None:
        super().__init__(code="INGESTION_FAILED", message=message, status_code=500)


class EscalationError(ArtrixError):
    def __init__(self, message: str = "Escalation failed") -> None:
        super().__init__(code="ESCALATION_FAILED", message=message, status_code=500)


class KnowledgeBaseEmptyError(ArtrixError):
    def __init__(self, message: str = "No knowledge base documents found for tenant") -> None:
        super().__init__(code="KNOWLEDGE_BASE_EMPTY", message=message, status_code=404)


class EmbeddingTimeoutError(ArtrixError):
    def __init__(self, message: str = "Embedding generation timed out") -> None:
        super().__init__(code="EMBEDDING_TIMEOUT", message=message, status_code=504)


class DatabaseConnectionError(ArtrixError):
    def __init__(self, message: str = "Database connection failed") -> None:
        super().__init__(code="DATABASE_CONNECTION_ERROR", message=message, status_code=503)


class RedisConnectionError(ArtrixError):
    def __init__(self, message: str = "Redis connection failed") -> None:
        super().__init__(code="REDIS_CONNECTION_ERROR", message=message, status_code=503)


class QdrantConnectionError(ArtrixError):
    def __init__(self, message: str = "Qdrant connection failed") -> None:
        super().__init__(code="QDRANT_CONNECTION_ERROR", message=message, status_code=503)


class InvalidFileTypeError(ArtrixError):
    def __init__(self, message: str = "Unsupported file type") -> None:
        super().__init__(code="INVALID_FILE_TYPE", message=message, status_code=400)


class DocumentNotFoundError(ArtrixError):
    def __init__(self, message: str = "Document not found") -> None:
        super().__init__(code="DOCUMENT_NOT_FOUND", message=message, status_code=404)
