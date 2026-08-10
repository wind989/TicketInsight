"""The human semantic-review path accepts numeric scores only and never stores prose."""

from __future__ import annotations

import json

import pytest

from app.services.semantic_review import SCORE_DIMENSIONS, SemanticReviewError, summarize_semantic_review_file


def _completed_payload() -> dict[str, object]:
    return {
        "version": "semantic-review-v1",
        "items": [
            {"id": f"Q{index:02d}", "scores": {dimension: 4 for dimension in SCORE_DIMENSIONS}}
            for index in range(1, 16)
        ],
    }


def test_completed_numeric_review_aggregates_without_copying_item_content(tmp_path):
    path = tmp_path / "review.json"
    path.write_text(json.dumps(_completed_payload()), encoding="utf-8")

    summary = summarize_semantic_review_file(path)

    assert summary["complete"] is True
    assert summary["completed_review_count"] == 15
    assert summary["dimensions"]["directness"] == {"scored_items": 15, "average_score": 4.0}
    assert "items" not in summary and "question" not in summary and "conclusion" not in summary


def test_incomplete_or_free_form_review_is_refused(tmp_path):
    incomplete = _completed_payload()
    incomplete["items"][0]["scores"]["directness"] = None  # type: ignore[index]
    incomplete_path = tmp_path / "incomplete.json"
    incomplete_path.write_text(json.dumps(incomplete), encoding="utf-8")
    with pytest.raises(SemanticReviewError):
        summarize_semantic_review_file(incomplete_path)

    free_form = _completed_payload()
    free_form["items"][0]["comment"] = "not allowed"  # type: ignore[index]
    free_form_path = tmp_path / "free-form.json"
    free_form_path.write_text(json.dumps(free_form), encoding="utf-8")
    with pytest.raises(SemanticReviewError):
        summarize_semantic_review_file(free_form_path)
