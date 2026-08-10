"""Run the fixed SQL-safety set and write a safe, reproducible JSON report."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.evaluation import evaluate_sql_safety


def main() -> int:
    report = evaluate_sql_safety()
    report["executed_at"] = datetime.now(timezone.utc).isoformat()
    report_path = ROOT / "reports" / "sql_safety_evaluation.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path), "total": report["total"], "passed": report["passed"]}, ensure_ascii=False))
    return 0 if report["total"] == report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
