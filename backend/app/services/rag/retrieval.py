"""Hybrid search + reranking retrieval pipeline.

Full implementation of Section 7 from agents.md.

Pipeline: dense_retrieval + sparse_retrieval → RRF merge → Cohere rerank
          → confidence scoring → escalation decision

Public API:
    - RetrievalService.retrieve(query, tenant_id, tenant_config) → RetrievalOutput
    - invalidate_bm25_cache(tenant_id, redis) → None
    - compute_confidence(rerank_results) → float
    - should_escalate(confidence, turn_count, max_turns, threshold) → tuple
"""

from __future__ import annotations

import asyncio
import base64
import pickle
import time
import uuid
from dataclasses import dataclass
from typing import Any

import cohere
import structlog
from rank_bm25 import BM25Okapi

from app.core.config import settings
from app.db.qdrant import QdrantService
from app.db.redis import RedisClient
from app.services.llm.base import LLMProvider

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BM25_CACHE_TTL = 3600        # 1 hour
_BM25_CACHE_PREFIX = "bm25_index"
_RRF_K = 60                   # RRF constant
_DENSE_LIMIT = 20             # per-search limit for each Qdrant vector type
_RRF_TOP_N = 40               # candidates passed to reranker
_RERANK_TOP_N = 8             # final results after Cohere rerank
_RERANK_TIMEOUT = 10.0        # seconds

_VECTOR_TYPES = ("raw", "summary", "hypothetical")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RetrievalResult:
    """Intermediate result from dense or sparse retrieval."""

    chunk_id: str
    text: str
    payload: dict[str, Any]
    dense_score: float = 0.0
    sparse_score: float = 0.0


@dataclass
class RankedResult:
    """Final ranked result after Cohere reranking."""

    chunk_id: str
    text: str
    payload: dict[str, Any]
    relevance_score: float
    rank: int


@dataclass
class RetrievalOutput:
    """Complete output from the retrieval pipeline."""

    results: list[RankedResult]
    confidence: float
    should_escalate: bool
    escalation_reason: str | None
    retrieval_latency_ms: int


@dataclass
class _BM25CacheEntry:
    """Cached BM25 index + metadata for a tenant. Pickled into Redis."""

    bm25: BM25Okapi
    chunk_ids: list[str]
    chunk_texts: list[str]
    payloads: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Module-level Cohere client (lazy singleton)
# ---------------------------------------------------------------------------

_cohere_client: cohere.AsyncClient | None = None


def _get_cohere_client() -> cohere.AsyncClient:
    """Lazy-initialize the Cohere async client."""
    global _cohere_client
    if _cohere_client is None:
        _cohere_client = cohere.AsyncClient(api_key=settings.cohere_api_key)
    return _cohere_client


# ---------------------------------------------------------------------------
# 4f — Confidence Scoring (Section 7.2 — exact formula, do not modify)
# ---------------------------------------------------------------------------

def compute_confidence(rerank_results: list[RankedResult]) -> float:
    """Compute retrieval confidence from rerank results.

    Formula: top_score * 0.85 + (supporting_count / 10) * 0.15
    where supporting_count = results with relevance_score > 0.4.
    """
    if not rerank_results:
        return 0.0
    top_score = rerank_results[0].relevance_score
    supporting = sum(1 for r in rerank_results if r.relevance_score > 0.4)
    return min(1.0, top_score * 0.85 + (supporting / 10) * 0.15)


# ---------------------------------------------------------------------------
# 4g — Escalation Decision (Section 7.3 — tenant-configurable thresholds)
# ---------------------------------------------------------------------------

def should_escalate(
    confidence: float,
    turn_count: int,
    max_turns: int,
    escalate_threshold: float,
) -> tuple[bool, str | None]:
    """Determine if the conversation should be escalated.

    Thresholds are per-tenant, passed explicitly by the caller.
    """
    if confidence < escalate_threshold:
        return True, "low_retrieval_confidence"
    if turn_count >= max_turns:
        return True, "max_turns_exceeded"
    return False, None


# ---------------------------------------------------------------------------
# BM25 Cache Helpers (4a)
# ---------------------------------------------------------------------------

def _bm25_cache_key(tenant_id: str | uuid.UUID) -> str:
    """Redis key for a tenant's BM25 index cache."""
    return f"{_BM25_CACHE_PREFIX}:{tenant_id}"


def _tokenize(text: str) -> list[str]:
    """Simple whitespace + lowercase tokenizer for BM25."""
    return text.lower().split()


async def invalidate_bm25_cache(
    tenant_id: str | uuid.UUID,
    redis: RedisClient,
) -> None:
    """Delete the cached BM25 index for a tenant.

    Must be called at the end of every successful ingestion run
    so subsequent retrievals rebuild with new data.
    """
    key = _bm25_cache_key(tenant_id)
    await redis.delete(key)
    logger.info("bm25_cache_invalidated", tenant_id=str(tenant_id))


# ===================================================================
# RetrievalService (4h — single public method)
# ===================================================================

class RetrievalService:
    """Hybrid retrieval pipeline: dense + sparse → RRF → rerank → confidence.

    Single public method: ``retrieve()``. All internals are private.
    """

    def __init__(
        self,
        llm: LLMProvider,
        qdrant: QdrantService,
        redis: RedisClient,
    ) -> None:
        self._llm = llm
        self._qdrant = qdrant
        self._redis = redis

    # ── Public interface ────────────────────────────────────────────

    async def retrieve(
        self,
        query: str,
        tenant_id: str | uuid.UUID,
        tenant_config: dict[str, Any],
    ) -> RetrievalOutput:
        """Run full hybrid retrieval pipeline.

        Args:
            query: User's search query text.
            tenant_id: Tenant UUID (str or uuid.UUID).
            tenant_config: Tenant configuration dict containing:
                - escalation_threshold (float, default 0.55)
                - max_turns_before_escalation (int, default 10)
                - turn_count (int, current conversation turn count)

        Returns:
            RetrievalOutput with ranked results, confidence, and escalation info.
        """
        start = time.monotonic()
        tid = str(tenant_id)
        await self._qdrant.create_collection_if_not_exists(tid)

        # Fast exit: if collection is empty, skip entire pipeline
        point_count = await self._qdrant.collection_point_count(tid)
        if point_count == 0:
            latency_ms = int((time.monotonic() - start) * 1000)
            logger.debug("retrieval_empty_collection", tenant_id=tid, latency_ms=latency_ms)
            return RetrievalOutput(
                results=[],
                confidence=0.0,
                should_escalate=False,
                escalation_reason=None,
                retrieval_latency_ms=latency_ms,
            )

        # 1. Parallel dense + sparse retrieval
        dense_results, sparse_results = await asyncio.gather(
            self._dense_retrieval(query, tid),
            self._sparse_retrieval(query, tid),
        )

        # 2. Reciprocal Rank Fusion
        merged = self._reciprocal_rank_fusion(dense_results, sparse_results)

        # 3. Cohere rerank (top 40 → top 8)
        ranked = await self._rerank(query, merged[:_RRF_TOP_N])

        # 4. Confidence scoring
        confidence = compute_confidence(ranked)

        # 5. Escalation decision
        turn_count = tenant_config.get("turn_count", 0)
        max_turns = tenant_config.get("max_turns_before_escalation", 10)
        escalate_threshold = tenant_config.get("escalation_threshold", 0.55)
        escalate, reason = should_escalate(
            confidence, turn_count, max_turns, escalate_threshold
        )

        latency_ms = int((time.monotonic() - start) * 1000)

        logger.info(
            "retrieval_complete",
            tenant_id=tid,
            dense_count=len(dense_results),
            sparse_count=len(sparse_results),
            merged_count=len(merged),
            ranked_count=len(ranked),
            confidence=round(confidence, 3),
            should_escalate=escalate,
            latency_ms=latency_ms,
        )

        return RetrievalOutput(
            results=ranked,
            confidence=confidence,
            should_escalate=escalate,
            escalation_reason=reason,
            retrieval_latency_ms=latency_ms,
        )

    # ── 4b. Dense retrieval ─────────────────────────────────────────

    async def _dense_retrieval(
        self, query: str, tenant_id: str
    ) -> list[RetrievalResult]:
        """Embed query and search Qdrant across all 3 vector types.

        Runs 3 parallel searches (raw, summary, hypothetical), each
        with limit=20 and is_latest_version=True filter.
        Deduplicates by chunk_id, keeping the highest scoring hit.
        """
        query_vector = await self._llm.embed(query)

        search_tasks = [
            self._qdrant.search(
                tenant_id=tenant_id,
                query_vector=query_vector,
                limit=_DENSE_LIMIT,
                filters={"is_latest_version": True, "vector_type": vtype},
            )
            for vtype in _VECTOR_TYPES
        ]
        results_lists = await asyncio.gather(*search_tasks)

        # Deduplicate by chunk_id — keep highest score per chunk
        best_by_chunk: dict[str, RetrievalResult] = {}
        for hits in results_lists:
            for hit in hits:
                payload = hit["payload"]
                chunk_id = payload.get("chunk_id", hit["id"])
                score = hit["score"]

                if (
                    chunk_id not in best_by_chunk
                    or score > best_by_chunk[chunk_id].dense_score
                ):
                    best_by_chunk[chunk_id] = RetrievalResult(
                        chunk_id=chunk_id,
                        text=payload.get("chunk_text", ""),
                        payload=payload,
                        dense_score=score,
                    )

        results = sorted(
            best_by_chunk.values(),
            key=lambda r: r.dense_score,
            reverse=True,
        )

        logger.debug(
            "dense_retrieval_done",
            tenant_id=tenant_id,
            total_hits=sum(len(r) for r in results_lists),
            unique_chunks=len(results),
        )
        return results

    # ── 4a / 4c. Sparse retrieval (BM25) ───────────────────────────

    async def _sparse_retrieval(
        self, query: str, tenant_id: str
    ) -> list[RetrievalResult]:
        """Score query against tenant's BM25 index. Returns top 20 by BM25 score."""
        cache_entry = await self._get_or_build_bm25(tenant_id)
        if cache_entry is None or cache_entry.bm25.corpus_size == 0:
            logger.debug("bm25_empty_corpus", tenant_id=tenant_id)
            return []

        tokenized_query = _tokenize(query)
        scores = cache_entry.bm25.get_scores(tokenized_query)

        # Sort by score descending, take top 20
        indexed_scores = sorted(
            enumerate(scores), key=lambda x: x[1], reverse=True
        )[:_DENSE_LIMIT]

        results: list[RetrievalResult] = []
        for idx, score in indexed_scores:
            if score <= 0.0:
                continue
            results.append(RetrievalResult(
                chunk_id=cache_entry.chunk_ids[idx],
                text=cache_entry.chunk_texts[idx],
                payload=cache_entry.payloads[idx],
                sparse_score=float(score),
            ))

        logger.debug(
            "sparse_retrieval_done",
            tenant_id=tenant_id,
            corpus_size=cache_entry.bm25.corpus_size,
            result_count=len(results),
        )
        return results

    async def _get_or_build_bm25(
        self, tenant_id: str
    ) -> _BM25CacheEntry | None:
        """Load BM25 index from Redis cache, or build from Qdrant and cache.

        On cache miss: scrolls all raw vectors from Qdrant, builds BM25Okapi,
        serializes via pickle + base64, stores in Redis with TTL of 3600s.
        """
        cache_key = _bm25_cache_key(tenant_id)

        # Try cache first
        cached_raw = await self._redis.get(cache_key)
        if cached_raw is not None:
            try:
                data: _BM25CacheEntry = pickle.loads(
                    base64.b64decode(cached_raw.encode("ascii"))
                )
                logger.debug("bm25_cache_hit", tenant_id=tenant_id)
                return data
            except Exception as e:
                logger.warning(
                    "bm25_cache_deserialize_failed",
                    tenant_id=tenant_id,
                    error=str(e),
                )

        # Cache miss — build from Qdrant (raw vectors only)
        logger.info("bm25_cache_miss_rebuilding", tenant_id=tenant_id)
        points = await self._qdrant.scroll_all(
            tenant_id=tenant_id,
            filters={"is_latest_version": True, "vector_type": "raw"},
        )

        if not points:
            logger.debug("bm25_no_points", tenant_id=tenant_id)
            return None

        chunk_ids: list[str] = []
        chunk_texts: list[str] = []
        payloads: list[dict[str, Any]] = []
        tokenized_corpus: list[list[str]] = []

        for point in points:
            payload = point["payload"]
            text = payload.get("chunk_text", "")
            if not text:
                continue
            chunk_ids.append(payload.get("chunk_id", point["id"]))
            chunk_texts.append(text)
            payloads.append(payload)
            tokenized_corpus.append(_tokenize(text))

        if not tokenized_corpus:
            return None

        bm25 = BM25Okapi(tokenized_corpus)
        entry = _BM25CacheEntry(
            bm25=bm25,
            chunk_ids=chunk_ids,
            chunk_texts=chunk_texts,
            payloads=payloads,
        )

        # Store in Redis
        try:
            serialized = base64.b64encode(pickle.dumps(entry)).decode("ascii")
            await self._redis.set_with_ttl(
                cache_key, serialized, _BM25_CACHE_TTL
            )
            logger.info(
                "bm25_cache_built",
                tenant_id=tenant_id,
                corpus_size=len(chunk_ids),
            )
        except Exception as e:
            logger.warning("bm25_cache_store_failed", error=str(e))

        return entry

    # ── 4d. Reciprocal Rank Fusion ──────────────────────────────────

    @staticmethod
    def _reciprocal_rank_fusion(
        dense: list[RetrievalResult],
        sparse: list[RetrievalResult],
        k: int = _RRF_K,
    ) -> list[RetrievalResult]:
        """Merge dense + sparse results using Reciprocal Rank Fusion (k=60).

        RRF score = Σ 1/(k + rank) across all lists a chunk appears in.
        Chunks appearing in only one list still participate with their
        rank from that list only. Returns top 40 candidates by RRF score.
        """
        rrf_scores: dict[str, float] = {}
        result_map: dict[str, RetrievalResult] = {}

        # Dense results (already sorted by dense_score descending)
        for rank, r in enumerate(dense, start=1):
            rrf_scores[r.chunk_id] = (
                rrf_scores.get(r.chunk_id, 0.0) + 1.0 / (k + rank)
            )
            if r.chunk_id not in result_map:
                result_map[r.chunk_id] = r

        # Sparse results (already sorted by sparse_score descending)
        for rank, r in enumerate(sparse, start=1):
            rrf_scores[r.chunk_id] = (
                rrf_scores.get(r.chunk_id, 0.0) + 1.0 / (k + rank)
            )
            if r.chunk_id not in result_map:
                result_map[r.chunk_id] = r
            else:
                # Merge sparse score into existing result
                existing = result_map[r.chunk_id]
                result_map[r.chunk_id] = RetrievalResult(
                    chunk_id=r.chunk_id,
                    text=existing.text or r.text,
                    payload=existing.payload or r.payload,
                    dense_score=existing.dense_score,
                    sparse_score=r.sparse_score,
                )

        # Sort by RRF score descending
        sorted_ids = sorted(
            rrf_scores.keys(),
            key=lambda cid: rrf_scores[cid],
            reverse=True,
        )

        merged = [result_map[cid] for cid in sorted_ids[:_RRF_TOP_N]]

        logger.debug(
            "rrf_merge_done",
            dense_count=len(dense),
            sparse_count=len(sparse),
            merged_count=len(merged),
        )
        return merged

    # ── 4e. Cohere Reranking ────────────────────────────────────────

    async def _rerank(
        self, query: str, candidates: list[RetrievalResult]
    ) -> list[RankedResult]:
        """Rerank candidates via Cohere rerank-english-v3.0.

        On timeout (10s) or any Cohere API failure: falls back to top 8
        RRF results without reranking. Logged but never raises.
        """
        if not candidates:
            return []

        try:
            co = _get_cohere_client()
            response = await asyncio.wait_for(
                co.rerank(
                    model="rerank-english-v3.0",
                    query=query,
                    documents=[c.text for c in candidates],
                    top_n=_RERANK_TOP_N,
                ),
                timeout=_RERANK_TIMEOUT,
            )

            ranked: list[RankedResult] = []
            for rank_idx, result in enumerate(response.results):
                candidate = candidates[result.index]
                ranked.append(RankedResult(
                    chunk_id=candidate.chunk_id,
                    text=candidate.text,
                    payload=candidate.payload,
                    relevance_score=result.relevance_score,
                    rank=rank_idx + 1,
                ))

            logger.debug(
                "cohere_rerank_done",
                input_count=len(candidates),
                output_count=len(ranked),
                top_score=ranked[0].relevance_score if ranked else 0.0,
            )
            return ranked

        except asyncio.TimeoutError:
            logger.warning(
                "cohere_rerank_timeout", timeout=_RERANK_TIMEOUT
            )
            return self._fallback_rank(candidates)
        except Exception as e:
            logger.warning("cohere_rerank_failed", error=str(e))
            return self._fallback_rank(candidates)

    @staticmethod
    def _fallback_rank(
        candidates: list[RetrievalResult],
    ) -> list[RankedResult]:
        """Fall back to top 8 RRF results when Cohere reranking fails.

        Uses dense_score as a proxy for relevance_score.
        """
        ranked: list[RankedResult] = []
        for rank_idx, c in enumerate(candidates[:_RERANK_TOP_N]):
            ranked.append(RankedResult(
                chunk_id=c.chunk_id,
                text=c.text,
                payload=c.payload,
                relevance_score=max(c.dense_score, 0.0),
                rank=rank_idx + 1,
            ))
        return ranked
