"""Abstract LLM provider interface.

All LLM implementations must inherit from this class.
Business logic never imports a concrete provider directly.
The concrete provider is instantiated once in the FastAPI lifespan
and injected everywhere via Depends().
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass(frozen=True)
class LLMResponse:
    """Structured response from an LLM call, including token usage."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.3,
    ) -> LLMResponse:
        """Generate a complete response from the LLM.

        Args:
            prompt: The user/input prompt text.
            system_prompt: System-level instructions for the model.
            max_tokens: Maximum tokens in the generated response.
            temperature: Sampling temperature (0.0–1.0).

        Returns:
            LLMResponse with text content and token usage counts.

        Raises:
            RuntimeError: If the LLM call fails after timeout or API error.
        """
        ...

    @abstractmethod
    async def stream(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        """Stream response tokens from the LLM.

        Yields string deltas as they arrive. Caller is responsible for
        concatenating them into the full response.

        Args:
            prompt: The user/input prompt text.
            system_prompt: System-level instructions for the model.
            max_tokens: Maximum tokens in the generated response.
            temperature: Sampling temperature (0.0–1.0).

        Yields:
            String chunks of the response as they are generated.

        Raises:
            RuntimeError: If the LLM streaming call fails.
        """
        ...
        # Make the type checker happy — this is never reached
        yield ""  # pragma: no cover

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for the given text.

        Args:
            text: The text to embed.

        Returns:
            A list of floats representing the embedding vector.

        Raises:
            RuntimeError: If the embedding call fails.
        """
        ...
