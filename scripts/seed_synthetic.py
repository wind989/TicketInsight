"""Load fixed synthetic/de-identified TicketInsight data after migrations succeed."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.database import SessionLocal
from app.services.seed import seed_synthetic_data


def main() -> int:
    session = SessionLocal()
    try:
        print(json.dumps(seed_synthetic_data(session), ensure_ascii=False))
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
