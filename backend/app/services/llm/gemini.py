"""Google Gemini LLM provider implementation.

Uses google-generativeai SDK with Gemini Flash model.
Instantiated once via dependency injection in app/api/deps.py.
All external calls have a 10-second timeout and structured error logging.
"""

import asyncio
from typing import AsyncIterator

import google.generativeai as genai
import structlog

from app.core.exceptions import EmbeddingTimeoutError
from app.services.llm.base import LLMProvider, LLMResponse

logger = structlog.get_logger(__name__)

_TIMEOUT_SECONDS = 10
_EMBEDDING_MODEL = "models/gemini-embedding-001"


class GeminiProvider(LLMProvider):
    """Gemini 1.5 Flash implementation of LLMProvider."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        genai.configure(api_key=api_key)
        self._model_name = model
        logger.info("gemini_provider_initialized", model=model)

    def _build_model(self, system_prompt: str) -> genai.GenerativeModel:
        """Build a GenerativeModel with the given system instruction."""
        return genai.GenerativeModel(
            model_name=self._model_name,
            system_instruction=system_prompt or None,
        )

    async def generate(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.3,
    ) -> LLMResponse:
        """Generate a complete response using Gemini Flash."""
        model = self._build_model(system_prompt)
        generation_config = genai.GenerationConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
        )
        try:
            response = await model.generate_content_async(
                prompt,
                generation_config=generation_config,
                request_options={"timeout": _TIMEOUT_SECONDS},
            )
            # Safe text extraction — response.text throws when Gemini
            # returns no valid Part (safety block, empty candidates).
            try:
                text = response.text
            except (ValueError, AttributeError):
                # Extract from candidates manually if .text accessor fails
                text = ""
                if response.candidates:
                    try:
                        for part in response.candidates[0].content.parts:
                            if hasattr(part, "text") and part.text:
                                text += part.text
                    except (IndexError, AttributeError):
                        pass
                if not text:
                    logger.warning(
                        "gemini_empty_response",
                        prompt_len=len(prompt),
                        candidates=len(response.candidates) if response.candidates else 0,
                    )
            usage = response.usage_metadata
            result = LLMResponse(
                text=text,
                input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
                output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
            )
            logger.debug(
                "gemini_generate_ok",
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                prompt_len=len(prompt),
            )
            return result
        except Exception as e:
            logger.error(
                "gemini_generate_failed",
                error=str(e),
                model=self._model_name,
                prompt_len=len(prompt),
            )
            raise RuntimeError(f"Gemini generate failed: {e}") from e

    async def stream(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        """Stream response tokens from Gemini Flash."""
        model = self._build_model(system_prompt)
        generation_config = genai.GenerationConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
        )
        try:
            response = await model.generate_content_async(
                prompt,
                generation_config=generation_config,
                stream=True,
                request_options={"timeout": _TIMEOUT_SECONDS},
            )
            async for chunk in response:
                if chunk.text:
                    yield chunk.text
            logger.debug("gemini_stream_ok", prompt_len=len(prompt))
        except Exception as e:
            logger.error(
                "gemini_stream_failed",
                error=str(e),
                model=self._model_name,
                prompt_len=len(prompt),
            )
            raise RuntimeError(f"Gemini stream failed: {e}") from e

    async def embed(self, text: str) -> list[float]:
        """Generate embedding using Google gemini-embedding-001.

        The genai.embed_content SDK call is synchronous, so we run it
        in a thread pool to avoid blocking the async event loop.
        Wrapped in asyncio.wait_for with a 10-second timeout.
        """
        try:
            result: dict = await asyncio.wait_for(
                asyncio.to_thread(
                    genai.embed_content,
                    model=_EMBEDDING_MODEL,
                    content=text,
                    task_type="retrieval_document",
                ),
                timeout=_TIMEOUT_SECONDS,
            )
            embedding: list[float] = result["embedding"]
            logger.debug(
                "gemini_embed_ok",
                text_len=len(text),
                vector_dim=len(embedding),
            )
            return embedding
        except asyncio.TimeoutError as e:
            logger.error(
                "gemini_embed_timeout",
                text_len=len(text),
                timeout_seconds=_TIMEOUT_SECONDS,
            )
            raise EmbeddingTimeoutError(
                f"Embedding timed out after {_TIMEOUT_SECONDS}s"
            ) from e
        except EmbeddingTimeoutError:
            raise
        except Exception as e:
            logger.error(
                "gemini_embed_failed",
                error=str(e),
                text_len=len(text),
            )
            raise RuntimeError(f"Gemini embed failed: {e}") from e
