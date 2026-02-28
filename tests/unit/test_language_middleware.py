"""Unit tests for language middleware (Phase 1 passthrough).

Tests:
  - detect_language returns "en" for any input
  - translate_to_english returns input unchanged
  - translate_from_english returns input unchanged
  - None/empty input does not raise (handle gracefully)
"""

from __future__ import annotations

import pytest

from app.services.language.middleware import LanguageMiddleware


@pytest.mark.asyncio
class TestLanguageMiddleware:
    """Tests for Phase 1 passthrough language middleware."""

    async def test_detect_language_returns_english(self) -> None:
        mw = LanguageMiddleware()
        assert await mw.detect_language("Hello world") == "en"

    async def test_detect_language_non_english_still_returns_en(self) -> None:
        mw = LanguageMiddleware()
        assert await mw.detect_language("Namaste duniya") == "en"

    async def test_translate_to_english_passthrough(self) -> None:
        mw = LanguageMiddleware()
        text = "How do I return my order?"
        assert await mw.translate_to_english(text, "en") == text

    async def test_translate_from_english_passthrough(self) -> None:
        mw = LanguageMiddleware()
        text = "Your order has been shipped."
        assert await mw.translate_from_english(text, "en") == text

    async def test_translate_to_english_with_different_lang(self) -> None:
        mw = LanguageMiddleware()
        text = "Some Hindi text"
        # Phase 1: passthrough regardless of source_lang
        assert await mw.translate_to_english(text, "hi") == text

    async def test_translate_from_english_with_different_lang(self) -> None:
        mw = LanguageMiddleware()
        text = "Response text"
        # Phase 1: passthrough regardless of target_lang
        assert await mw.translate_from_english(text, "hi") == text

    async def test_empty_string_does_not_raise(self) -> None:
        mw = LanguageMiddleware()
        assert await mw.detect_language("") == "en"
        assert await mw.translate_to_english("", "en") == ""
        assert await mw.translate_from_english("", "en") == ""
