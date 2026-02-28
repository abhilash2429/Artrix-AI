"""Unit tests for confidence scoring logic.

Tests:
  - Empty results → 0.0
  - Single result with score 1.0 → exactly 0.85
  - Single result with score 0.0 → 0.0
  - 10 results all above 0.4 → score = top_score * 0.85 + 0.15
  - Results below 0.4 do not count toward supporting chunks
"""

from __future__ import annotations

import pytest

from app.services.rag.retrieval import RankedResult, compute_confidence


def _make_ranked_result(score: float) -> RankedResult:
    """Create a RankedResult with the given relevance score."""
    return RankedResult(
        chunk_id="test-chunk",
        text="test text",
        payload={},
        relevance_score=score,
        rank=0,
    )


class TestConfidenceScoring:
    """Tests for compute_confidence()."""

    def test_empty_results_returns_zero(self) -> None:
        """Empty results list should return 0.0."""
        assert compute_confidence([]) == 0.0

    def test_single_result_score_one(self) -> None:
        """Single result with score 1.0 → 1.0 * 0.85 + (1/10) * 0.15 = 0.865."""
        results = [_make_ranked_result(1.0)]
        confidence = compute_confidence(results)
        # 1.0 * 0.85 + (1/10) * 0.15 = 0.85 + 0.015 = 0.865
        assert confidence == pytest.approx(0.865, abs=0.001)

    def test_single_result_score_zero(self) -> None:
        """Single result with score 0.0 → 0.0 * 0.85 + 0 * 0.15 = 0.0."""
        results = [_make_ranked_result(0.0)]
        confidence = compute_confidence(results)
        assert confidence == 0.0

    def test_ten_results_all_above_threshold(self) -> None:
        """10 results all above 0.4 → score = top_score * 0.85 + (10/10) * 0.15."""
        results = [_make_ranked_result(0.9)] + [
            _make_ranked_result(0.5) for _ in range(9)
        ]
        confidence = compute_confidence(results)
        # 0.9 * 0.85 + (10/10) * 0.15 = 0.765 + 0.15 = 0.915
        assert confidence == pytest.approx(0.915, abs=0.001)

    def test_results_below_threshold_excluded(self) -> None:
        """Results with relevance_score <= 0.4 don't count as supporting."""
        results = [
            _make_ranked_result(0.8),  # top score, above 0.4
            _make_ranked_result(0.3),  # below 0.4
            _make_ranked_result(0.2),  # below 0.4
            _make_ranked_result(0.1),  # below 0.4
        ]
        confidence = compute_confidence(results)
        # top_score = 0.8, supporting = 1 (only the 0.8 is above 0.4)
        # 0.8 * 0.85 + (1/10) * 0.15 = 0.68 + 0.015 = 0.695
        assert confidence == pytest.approx(0.695, abs=0.001)

    def test_mixed_results(self) -> None:
        """Mix of above and below threshold results."""
        results = [
            _make_ranked_result(0.95),
            _make_ranked_result(0.6),
            _make_ranked_result(0.5),
            _make_ranked_result(0.3),
            _make_ranked_result(0.1),
        ]
        confidence = compute_confidence(results)
        # top_score = 0.95, supporting = 3 (0.95, 0.6, 0.5 are > 0.4)
        # 0.95 * 0.85 + (3/10) * 0.15 = 0.8075 + 0.045 = 0.8525
        assert confidence == pytest.approx(0.8525, abs=0.001)

    def test_confidence_capped_at_one(self) -> None:
        """Confidence should never exceed 1.0."""
        results = [_make_ranked_result(1.0)] + [
            _make_ranked_result(0.99) for _ in range(20)
        ]
        confidence = compute_confidence(results)
        assert confidence <= 1.0
