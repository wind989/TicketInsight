"""Write a numeric-only aggregate for a completed human semantic review."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.services.semantic_review import SemanticReviewError, summarize_semantic_review_file


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="completed numeric-only semantic review JSON")
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "semantic_review_summary.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input if args.input.is_absolute() else ROOT / args.input
    output_path = args.output if args.output.is_absolute() else ROOT / args.output
    try:
        summary = summarize_semantic_review_file(input_path, require_complete=True)
    except SemanticReviewError as error:
        raise SystemExit(f"Refusing to write a semantic report: {error}") from error
    summary["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(output_path), "completed": summary["completed_review_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
