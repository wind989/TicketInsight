"""Write a labelled offline-demo report without contacting a model, MySQL, Qdrant server, or external system."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.offline_demo import run_offline_demo


def main() -> int:
    report = run_offline_demo()
    report["executed_at"] = datetime.now(timezone.utc).isoformat()
    report_path = ROOT / "reports" / "offline_demo.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path), "mode": report["mode"], "status": report["status"]}, ensure_ascii=False))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
