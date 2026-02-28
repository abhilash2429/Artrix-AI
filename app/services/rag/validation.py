"""Post-retrieval and post-generation validation.

Validates retrieved chunks and generated responses for quality and safety.
"""

from typing import Any


class ValidationService:
    """Post-retrieval and post-generation validation."""

    async def validate_retrieval(
        self, chunks: list[dict[str, Any]], query: str
    ) -> list[dict[str, Any]]:
        """Filter out low-quality or irrelevant retrieved chunks."""
        raise NotImplementedError("Will be implemented in validation section")

    async def validate_response(
        self, response: str, source_chunks: list[dict[str, Any]]
    ) -> bool:
        """Validate that the generated response is grounded in source chunks."""
        raise NotImplementedError("Will be implemented in validation section")
