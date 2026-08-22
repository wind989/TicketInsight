"""Role-specific contracts for the fixed TicketInsight Agent graph."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas import reject_pii_text
from app.services.agent_workflow_types import AnalysisDraft, ReviewDecision, SQLPlan


AgentRole = Literal["sql_planner", "attribution_advisor", "reviewer"]

ROLE_PROMPTS: dict[AgentRole, str] = {
    "sql_planner": (
        "You are the SQL-planner role. Produce one candidate read-only query for deterministic validation; "
        "you never execute SQL and you never decide permissions."
    ),
    "attribution_advisor": (
        "You are the attribution-advisor role. Explain patterns only from bounded evidence and query rows; "
        "separate observations from hypotheses and state limitations."
    ),
    "reviewer": (
        "You are the reviewer role. Check evidence grounding, query availability, scope compliance, and limitation honesty; "
        "return only an allowed review decision."
    ),
}


class SQLPlanPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql: str = Field(min_length=1, max_length=4000)
    rationale: str = Field(min_length=1, max_length=1000)

    @field_validator("sql", "rationale")
    @classmethod
    def reject_transport_wrappers(cls, value: str) -> str:
        if "```" in value or "\x00" in value:
            raise ValueError("模型输出不能包含 Markdown 包裹或控制字符")
        return value.strip()

    def to_domain(self) -> SQLPlan:
        return SQLPlan(sql=self.sql, rationale=self.rationale)


class AnalysisDraftPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conclusion: str = Field(min_length=1, max_length=3000)
    limitations: str = Field(min_length=1, max_length=1500)

    @field_validator("conclusion", "limitations")
    @classmethod
    def validate_redacted_text(cls, value: str) -> str:
        return reject_pii_text(value) or ""

    def to_domain(self) -> AnalysisDraft:
        return AnalysisDraft(conclusion=self.conclusion, limitations=self.limitations)


class ReviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "revise_sql", "revise_conclusion"]

    def to_domain(self) -> ReviewDecision:
        return self.decision
