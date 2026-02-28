"""Language detection + translation passthrough.

Phase 1: All methods are passthroughs (English only).
Phase 3: Sarvam Translate API integration — only method internals change.

IMPORTANT: Every user message MUST pass through translate_to_english before
reaching the agent. Every agent response MUST pass through translate_from_english
before being returned to the user. This interface contract is mandatory.
"""


# Phase 1: passthrough only.
# Phase 3: replace method bodies with Sarvam AI API calls.
# Calling code in app/api/v1/chat.py must NOT change between phases.
# Only these method bodies change.
class LanguageMiddleware:
    """Language detection and translation layer."""

    async def detect_language(self, text: str) -> str:
        """Returns ISO 639-1 language code. Phase 1: always returns 'en'."""
        return "en"

    async def translate_to_english(self, text: str, source_lang: str) -> str:
        """Phase 1: passthrough. Phase 3: Sarvam Translate API call."""
        return text

    async def translate_from_english(self, text: str, target_lang: str) -> str:
        """Phase 1: passthrough. Phase 3: Sarvam Translate API call."""
        return text
