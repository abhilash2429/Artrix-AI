"""Cerebras LLM provider implementation.

Uses the OpenAI-compatible API at https://api.cerebras.ai/v1.
Model: gpt-oss-120b (primary runner).
All external calls have a 10-second timeout and structured error logging.
"""

import asyncio
from typing import AsyncIterator

import structlog
from openai import AsyncOpenAI

from app.core.exceptions import RateLimitExceededError
from app.services.llm.base import LLMProvider, LLMResponse

logger = structlog.get_logger(__name__)

_TIMEOUT_SECONDS = 10
_CEREBRAS_BASE_URL = "https://api.cerebras.ai/v1"


def _is_rate_limit(error_text: str) -> bool:
    text = error_text.lower()
    return "429" in text or "rate limit" in text or "quota" in text


class CerebrasProvider(LLMProvider):
    """Cerebras gpt-oss-120b via OpenAI-compatible API."""

    def __init__(self, api_key: str, model: str = "gpt-oss-120b") -> None:
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=_CEREBRAS_BASE_URL,
        )
        self._model = model
        logger.info("cerebras_provider_initialized", model=model)

    async def generate(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.3,
    ) -> LLMResponse:
        """Generate a complete response using Cerebras."""
        try:
            response = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature,
                ),
                timeout=_TIMEOUT_SECONDS,
            )
            text = response.choices[0].message.content or ""
            usage = response.usage
            result = LLMResponse(
                text=text,
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
            )
            logger.debug(
                "cerebras_generate_ok",
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                prompt_len=len(prompt),
            )
            return result
        except asyncio.TimeoutError as e:
            logger.error("cerebras_generate_timeout", prompt_len=len(prompt))
            raise RuntimeError("Cerebras generate timed out") from e
        except Exception as e:
            message = str(e)
            logger.error(
                "cerebras_generate_failed",
                error=message,
                model=self._model,
                prompt_len=len(prompt),
            )
            if _is_rate_limit(message):
                raise RateLimitExceededError(
                    "Cerebras rate limit exceeded. Retry later."
                ) from e
            raise RuntimeError(f"Cerebras generate failed: {e}") from e

    async def stream(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        """Cerebras free tier — no streaming. Falls back to generate() and yields the full text."""
        response = await self.generate(prompt, system_prompt, max_tokens, temperature)
        yield response.text

    async def embed(self, text: str) -> list[float]:
        """Cerebras does not support embeddings — raises NotImplementedError.

        Callers should use the Gemini provider for embed() via the
        FallbackLLMProvider which delegates embed() to Gemini.
        """
        raise NotImplementedError(
            "Cerebras does not support embeddings. Use Gemini for embed()."
        )
