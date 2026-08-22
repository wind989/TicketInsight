"""Small domain contracts shared by the graph and model adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ReviewDecision = Literal["approved", "revise_sql", "revise_conclusion"]


@dataclass(frozen=True)
class SQLPlan:
    sql: str
    rationale: str


@dataclass(frozen=True)
class AnalysisDraft:
    conclusion: str
    limitations: str
