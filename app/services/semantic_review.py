"""Validate and aggregate a privacy-preserving human semantic-review sheet."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.evaluation import load_question_set


SCORE_DIMENSIONS = ("directness", "evidence_grounding", "limitation_honesty")
SCORE_MIN = 1
SCORE_MAX = 5


class SemanticReviewError(ValueError):
    """Raised when a review is incomplete, malformed, or includes free-form content."""


def expected_question_ids() -> tuple[str, ...]:
    return tuple(item["id"] for item in load_question_set()["questions"])


def _validated_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if set(payload) != {"version", "items"} or payload["version"] != "semantic-review-v1":
        raise SemanticReviewError("评审文件版本或顶层字段不符合约定")
    items = payload.get("items")
    if not isinstance(items, list):
        raise SemanticReviewError("评审条目必须是列表")

    expected_ids = set(expected_question_ids())
    seen_ids: set[str] = set()
    validated: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {"id", "scores"}:
            raise SemanticReviewError("评审条目只允许 ID 与三项数值评分，不允许备注或原始内容")
        item_id = item.get("id")
        scores = item.get("scores")
        if not isinstance(item_id, str) or item_id not in expected_ids or item_id in seen_ids:
            raise SemanticReviewError("评审 ID 不在固定题集内或出现重复")
        if not isinstance(scores, dict) or set(scores) != set(SCORE_DIMENSIONS):
            raise SemanticReviewError("每条评审必须恰好包含三项规定评分")

        checked_scores: dict[str, int | None] = {}
        for dimension in SCORE_DIMENSIONS:
            value = scores[dimension]
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or not SCORE_MIN <= value <= SCORE_MAX):
                raise SemanticReviewError("评分只能是 1 至 5 的整数或尚未评分的 null")
            checked_scores[dimension] = value
        seen_ids.add(item_id)
        validated.append({"id": item_id, "scores": checked_scores})

    if seen_ids != expected_ids:
        raise SemanticReviewError("评审必须覆盖固定题集的全部 15 个 ID")
    return validated


def summarize_semantic_review_file(path: Path, *, require_complete: bool = True) -> dict[str, Any]:
    """Return aggregates only; never copy questions, conclusions, SQL, or reviewer prose."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SemanticReviewError("评审文件无法读取为 JSON") from error
    if not isinstance(payload, dict):
        raise SemanticReviewError("评审文件必须是 JSON 对象")
    items = _validated_items(payload)
    completed_items = [item for item in items if all(item["scores"][dimension] is not None for dimension in SCORE_DIMENSIONS)]
    if require_complete and len(completed_items) != len(items):
        raise SemanticReviewError("评审尚未完成，不能生成正式语义质量指标")

    dimensions: dict[str, dict[str, int | float | None]] = {}
    for dimension in SCORE_DIMENSIONS:
        values = [item["scores"][dimension] for item in completed_items if item["scores"][dimension] is not None]
        dimensions[dimension] = {
            "scored_items": len(values),
            "average_score": round(sum(values) / len(values), 4) if values else None,
        }
    return {
        "review_set": "semantic-review-v1",
        "expected_question_count": len(items),
        "completed_review_count": len(completed_items),
        "complete": len(completed_items) == len(items),
        "score_range": {"min": SCORE_MIN, "max": SCORE_MAX},
        "dimensions": dimensions,
        "limitations": [
            "Contains numeric human ratings and aggregates only.",
            "Does not retain questions, SQL, query rows, evidence excerpts, model output, reviewer notes, or credentials.",
            "Scores apply only to the fixed local synthetic/de-identified question set.",
        ],
    }
