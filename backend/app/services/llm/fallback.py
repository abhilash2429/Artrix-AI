"""Fallback LLM provider — tries primary, falls back to secondary on failure.

Cerebras (primary) handles generate() and stream().
Gemini (secondary) handles embed() always, and generate()/stream() on Cerebras failure.
"""

from typing import AsyncIterator

import structlog

from app.services.llm.base import LLMProvider, LLMResponse

logger = structlog.get_logger(__name__)


class FallbackLLMProvider(LLMProvider):
    """Tries primary provider first; falls back to secondary on any error.

    embed() always delegates to the secondary (Gemini) since
    Cerebras does not offer an embedding API.
    """

    def __init__(self, primary: LLMProvider, secondary: LLMProvider) -> None:
        self._primary = primary
        self._secondary = secondary
        logger.info(
            "fallback_provider_initialized",
            primary=type(primary).__name__,
            secondary=type(secondary).__name__,
        )

    async def generate(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.3,
    ) -> LLMResponse:
        """Try primary generate(); fall back to secondary on failure."""
        try:
            return await self._primary.generate(
                prompt, system_prompt, max_tokens, temperature
            )
        except Exception as primary_err:
            logger.warning(
                "primary_generate_failed_falling_back",
                primary=type(self._primary).__name__,
                error=str(primary_err),
            )
            return await self._secondary.generate(
                prompt, system_prompt, max_tokens, temperature
            )

    async def stream(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        """Try primary stream(); fall back to secondary on failure."""
        try:
            async for chunk in self._primary.stream(
                prompt, system_prompt, max_tokens, temperature
            ):
                yield chunk
        except Exception as primary_err:
            logger.warning(
                "primary_stream_failed_falling_back",
                primary=type(self._primary).__name__,
                error=str(primary_err),
            )
            async for chunk in self._secondary.stream(
                prompt, system_prompt, max_tokens, temperature
            ):
                yield chunk

    async def embed(self, text: str) -> list[float]:
        """Always use secondary (Gemini) for embeddings."""
        return await self._secondary.embed(text)
