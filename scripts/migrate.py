"""Run TicketInsight Alembic migrations using only its configured local database URL."""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    action = sys.argv[1] if len(sys.argv) > 1 else "upgrade"
    if action == "upgrade":
        command.upgrade(config, "head")
    elif action == "current":
        command.current(config)
    else:
        raise SystemExit("usage: python scripts/migrate.py [upgrade|current]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
