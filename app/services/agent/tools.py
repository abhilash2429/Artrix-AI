"""Agent tool definitions and output formatting.

Tool functions: knowledge_retrieval, escalate_to_human, structured_data_lookup.
Called via AgentCore._build_tools() closures capturing service references.
Only invoked when IntentRouter returns DOMAIN_QUERY.
Never called for CONVERSATIONAL or OUT_OF_SCOPE intents.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import httpx
import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Output Formatters
# ---------------------------------------------------------------------------


def format_retrieval_output(
    confidence: float,
    results: list[dict[str, Any]],
) -> str:
    """Format retrieval results as plain text for the agent."""
    lines: list[str] = [f"CONFIDENCE: {confidence:.3f}", "SOURCES:"]
    for r in results:
        chunk_id = r.get("chunk_id", "unknown")
        filename = r.get("filename", "unknown")
        section = r.get("section_heading", "unknown")
        lines.append(f"{chunk_id} | {filename} | {section}")
    lines.append("CONTENT:")
    for r in results:
        lines.append(r.get("text", ""))
    return "\n".join(lines)


def format_escalation_output(reason: str) -> str:
    """Format escalation result string."""
    return f"ESCALATED: {reason}"


def format_lookup_result(response_data: Any) -> str:
    """Format successful structured data lookup."""
    return f"LOOKUP_RESULT: {json.dumps(response_data)}"


def format_lookup_failed(detail: str = "data webhook unavailable") -> str:
    """Format failed lookup."""
    return f"LOOKUP_FAILED: {detail}"


def format_lookup_unavailable() -> str:
    """Format unavailable lookup (no webhook configured)."""
    return "LOOKUP_UNAVAILABLE: enterprise has not configured live data access"


# ---------------------------------------------------------------------------
# Tool Functions (Section 8.3)
# ---------------------------------------------------------------------------


async def knowledge_retrieval(
    query: str,
    retrieval_service: Any,
    tenant_id: UUID,
    tenant_config: dict[str, Any],
) -> Any:
    """Tool 1: knowledge_retrieval — runs hybrid search + rerank pipeline.

    Input: user query string.
    Returns: RetrievalOutput with results, confidence, and escalation decision.
    """
    return await retrieval_service.retrieve(
        query=query,
        tenant_id=tenant_id,
        tenant_config=tenant_config,
    )


async def escalate_to_human(
    reason: str,
    escalation_service: Any,
    session_id: UUID,
    tenant_id: UUID,
    last_user_message: str,
    webhook_url: str | None,
    external_user_id: str | None,
) -> str:
    """Tool 2: escalate_to_human — triggers escalation flow.

    Fires webhook, marks session as 'escalated', returns confirmation.
    This tool ends the agent loop for that session.
    """
    await escalation_service.escalate(
        session_id=session_id,
        tenant_id=tenant_id,
        reason=reason,
        last_user_message=last_user_message,
        webhook_url=webhook_url,
        external_user_id=external_user_id,
    )
    return format_escalation_output(reason)


async def structured_data_lookup(
    lookup_type: str,
    identifier: str,
    data_webhook_url: str | None,
) -> str:
    """Tool 3: structured_data_lookup — calls enterprise data webhook.

    Input: lookup_type ('order_status' | 'appointment' | 'policy_number'),
           identifier string.
    Uses 5-second timeout. Returns LOOKUP_RESULT, LOOKUP_FAILED, or LOOKUP_UNAVAILABLE.
    """
    if not data_webhook_url:
        return format_lookup_unavailable()

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                data_webhook_url,
                json={"lookup_type": lookup_type, "identifier": identifier},
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            return format_lookup_result(response.json())
    except Exception as e:
        logger.warning(
            "structured_data_lookup_failed",
            lookup_type=lookup_type,
            identifier=identifier,
            error=str(e),
        )
        return format_lookup_failed(str(e))
