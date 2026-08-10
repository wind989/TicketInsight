"""Deterministic SQL AST gate for the future dedicated TicketInsight read-only account."""

from __future__ import annotations

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp


ALLOWED_COLUMNS: dict[str, frozenset[str]] = {
    "customers": frozenset({"id", "anonymous_id", "tier", "created_at"}),
    "product_modules": frozenset({"id", "name", "status", "created_at"}),
    "sla_policies": frozenset({"id", "category", "priority", "response_minutes", "resolution_minutes", "active", "created_at"}),
    "tickets": frozenset({"id", "category", "priority", "status", "customer_id", "module_id", "created_at", "first_response_at", "resolved_at"}),
    "ticket_events": frozenset({"id", "ticket_id", "event_type", "occurred_at", "actor_group"}),
    "service_knowledge": frozenset({"id", "source_type", "category", "module_id", "version", "created_at"}),
}
# sqlglot represents boolean conjunction as an exp.Func subclass; it is an operator, not a callable SQL function.
# TIMESTAMPDIFF is deliberately limited below to TicketInsight SLA duration checks.
ALLOWED_FUNCTIONS = (exp.Count, exp.Sum, exp.Min, exp.Max, exp.Avg, exp.And, exp.TimestampDiff)
TIMESTAMPDIFF_UNITS = frozenset({"MINUTE", "HOUR", "DAY"})
TIMESTAMPDIFF_TIME_COLUMNS = {"tickets": frozenset({"created_at", "first_response_at", "resolved_at"})}
CONTROLLED_TIME_LITERAL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2})?$")
COMMENT_RE = re.compile(r"--|/\*|\*/|(^|\s)#")
HIGH_RISK_TOKEN_RE = re.compile(r"\b(?:outfile|dumpfile|load_file|sleep|benchmark)\b", re.IGNORECASE)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")


class SQLSafetyError(ValueError):
    """Raised before any database connection is opened."""


@dataclass(frozen=True)
class ValidatedSQL:
    """A bounded single SELECT with a separately redacted audit representation."""

    sql: str
    audit_sql: str
    max_rows: int
    tables: tuple[str, ...]


def _reject(message: str) -> None:
    raise SQLSafetyError(message)


def _audit_sql(expression: exp.Expression) -> str:
    """Preserve SQL structure for audit while removing all string-literal content."""

    audit_expression = expression.copy()
    for literal in audit_expression.find_all(exp.Literal):
        if literal.is_string:
            literal.replace(exp.Literal.string("[redacted]"))
    return audit_expression.sql(dialect="mysql")


def _validate_tables(expression: exp.Select) -> tuple[dict[str, str], tuple[str, ...]]:
    tables = list(expression.find_all(exp.Table))
    if not tables:
        _reject("SQL 必须从已授权表读取")
    aliases: dict[str, str] = {}
    physical_tables: list[str] = []
    for table in tables:
        if table.db or table.catalog:
            _reject("禁止跨库或显式数据库名")
        name = table.name.lower()
        if name not in ALLOWED_COLUMNS:
            _reject(f"未授权表：{name}")
        alias = table.alias_or_name.lower()
        if alias in aliases and aliases[alias] != name:
            _reject("SQL 表别名重复")
        aliases[alias] = name
        physical_tables.append(name)
    return aliases, tuple(dict.fromkeys(physical_tables))


def _validate_columns(expression: exp.Select, aliases: dict[str, str], tables: tuple[str, ...]) -> None:
    selected_aliases = {
        selected.alias.lower()
        for selected in expression.expressions
        if isinstance(selected, exp.Alias) and selected.alias
    }
    for star in expression.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):
            _reject("禁止 SELECT *，必须使用字段白名单")
    for column in expression.find_all(exp.Column):
        name = column.name.lower()
        table_or_alias = column.table.lower()
        if not table_or_alias and name in selected_aliases:
            continue
        if table_or_alias:
            table = aliases.get(table_or_alias)
            if table is None:
                _reject(f"未授权表或别名：{table_or_alias}")
            if name not in ALLOWED_COLUMNS[table]:
                _reject(f"未授权字段：{table}.{name}")
            continue
        candidates = [table for table in tables if name in ALLOWED_COLUMNS[table]]
        if len(candidates) != 1:
            _reject(f"字段必须明确限定或不在白名单中：{name}")


def _validate_timestampdiff(function: exp.TimestampDiff, aliases: dict[str, str]) -> None:
    """Permit only a simple ticket-duration calculation with a fixed unit."""

    unit = function.args.get("unit")
    if not isinstance(unit, exp.Var) or str(unit.this).upper() not in TIMESTAMPDIFF_UNITS:
        _reject("TIMESTAMPDIFF unit is not approved")

    argument_tables: set[str] = set()
    for argument in (function.this, function.expression):
        if isinstance(argument, exp.Column):
            alias = argument.table.lower()
            table = aliases.get(alias)
            if not alias or table not in TIMESTAMPDIFF_TIME_COLUMNS or argument.name.lower() not in TIMESTAMPDIFF_TIME_COLUMNS[table]:
                _reject("TIMESTAMPDIFF accepts only qualified ticket timestamp columns")
            argument_tables.add(table)
            continue
        if isinstance(argument, exp.Literal) and argument.is_string and CONTROLLED_TIME_LITERAL_RE.fullmatch(str(argument.this)):
            continue
        _reject("TIMESTAMPDIFF arguments must be an approved timestamp column or fixed timestamp literal")
    if len(argument_tables) > 1:
        _reject("TIMESTAMPDIFF cannot compare timestamps from different tables")


def _validate_functions(expression: exp.Select, aliases: dict[str, str]) -> None:
    for function in expression.find_all(exp.Func):
        if not isinstance(function, ALLOWED_FUNCTIONS):
            _reject(f"未授权 SQL 函数：{type(function).__name__}")
        if isinstance(function, exp.TimestampDiff):
            _validate_timestampdiff(function, aliases)


def _bound_limit(expression: exp.Select, max_rows: int) -> None:
    limit = expression.args.get("limit")
    if limit is None:
        expression.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))
        return
    if limit.args.get("offset") is not None:
        _reject("禁止 OFFSET，避免不可控分页扫描")
    value = limit.expression
    if not isinstance(value, exp.Literal) or not value.is_int:
        _reject("LIMIT 必须是整数常量")
    requested = int(value.this)
    if requested < 1:
        _reject("LIMIT 必须大于零")
    if requested > max_rows:
        limit.set("expression", exp.Literal.number(max_rows))


def validate_readonly_select(candidate_sql: str, max_rows: int = 200) -> ValidatedSQL:
    """Parse and bound one MySQL SELECT without executing it or trusting model output."""

    if not candidate_sql or len(candidate_sql) > 4000:
        _reject("SQL 为空或超过长度限制")
    if COMMENT_RE.search(candidate_sql) or HIGH_RISK_TOKEN_RE.search(candidate_sql):
        _reject("SQL 包含注释或高风险关键字")
    try:
        expressions = sqlglot.parse(candidate_sql, read="mysql")
    except sqlglot.ParseError as error:
        raise SQLSafetyError("SQL 无法解析") from error
    if len(expressions) != 1 or not isinstance(expressions[0], exp.Select):
        _reject("只允许单条 SELECT")
    expression = expressions[0]
    if expression.args.get("with_") is not None or any(expression.find_all(exp.Subquery)):
        _reject("禁止 CTE 或子查询")
    if expression.args.get("into") is not None:
        _reject("禁止 SELECT INTO")
    if expression.args.get("locks"):
        _reject("禁止锁定读取")
    for literal in expression.find_all(exp.Literal):
        if literal.is_string and (EMAIL_RE.search(str(literal.this)) or PHONE_RE.search(str(literal.this))):
            _reject("SQL 条件不得包含明显个人信息")

    aliases, tables = _validate_tables(expression)
    _validate_columns(expression, aliases, tables)
    _validate_functions(expression, aliases)
    _bound_limit(expression, max_rows)
    safe_sql = expression.sql(dialect="mysql")
    return ValidatedSQL(sql=safe_sql, audit_sql=_audit_sql(expression), max_rows=max_rows, tables=tables)
