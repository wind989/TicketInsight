"""Deterministic synthetic data for P0 development and later fixed evaluations."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Customer, ProductModule, SLAPolicy, ServiceKnowledge, Ticket, TicketEvent


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=timezone.utc)


def _summary(session: Session, created: bool) -> dict[str, int | bool]:
    """Return counts only; demo APIs never expose data through logs."""

    def count(model) -> int:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)

    return {
        "created": created,
        "customers": count(Customer),
        "product_modules": count(ProductModule),
        "sla_policies": count(SLAPolicy),
        "tickets": count(Ticket),
        "ticket_events": count(TicketEvent),
        "service_knowledge": count(ServiceKnowledge),
    }


def seed_synthetic_data(session: Session) -> dict[str, int | bool]:
    """Insert a fixed, anonymous scenario once so later analysis is repeatable."""

    if session.scalar(select(Customer.id).limit(1)) is not None:
        return _summary(session, created=False)

    modules = [
        ProductModule(name="支付中心", description="支付、扣款与回调处理模块", status="active"),
        ProductModule(name="登录与账户", description="登录、验证与账户访问模块", status="active"),
        ProductModule(name="订单中心", description="订单状态与售后查询模块", status="active"),
    ]
    customers = [
        Customer(anonymous_id="anon-A001", tier="standard"),
        Customer(anonymous_id="anon-A002", tier="vip"),
        Customer(anonymous_id="anon-A003", tier="standard"),
        Customer(anonymous_id="anon-A004", tier="enterprise"),
    ]
    policies = [
        SLAPolicy(category="payment", priority="high", response_minutes=30, resolution_minutes=240),
        SLAPolicy(category="payment", priority="urgent", response_minutes=15, resolution_minutes=120),
        SLAPolicy(category="login", priority="high", response_minutes=60, resolution_minutes=480),
        SLAPolicy(category="order", priority="medium", response_minutes=240, resolution_minutes=1440),
    ]
    session.add_all([*modules, *customers, *policies])
    session.flush()

    payment, login, order = modules
    tickets = [
        Ticket(title="支付后订单仍待支付", body_redacted="支付完成后订单状态未在预期时间更新。", category="payment", priority="high", status="open", customer_id=customers[0].id, module_id=payment.id, created_at=_at(8, 9)),
        Ticket(title="支付结果页面加载失败", body_redacted="支付结果页显示加载失败，重复刷新仍未恢复。", category="payment", priority="high", status="open", customer_id=customers[1].id, module_id=payment.id, created_at=_at(8, 10)),
        Ticket(title="扣款成功但回调延迟", body_redacted="扣款已完成，业务状态回调延迟超过预期。", category="payment", priority="urgent", status="pending", customer_id=customers[2].id, module_id=payment.id, created_at=_at(7, 15), first_response_at=_at(7, 15, 10)),
        Ticket(title="支付方式切换后无法提交", body_redacted="切换支付方式后提交操作失败。", category="payment", priority="medium", status="resolved", customer_id=customers[3].id, module_id=payment.id, created_at=_at(3, 11), first_response_at=_at(3, 11, 30), resolved_at=_at(3, 14)),
        Ticket(title="登录验证码未生效", body_redacted="输入验证码后仍提示验证失败。", category="login", priority="high", status="open", customer_id=customers[0].id, module_id=login.id, created_at=_at(8, 8)),
        Ticket(title="登录状态频繁失效", body_redacted="短时间内多次要求重新登录。", category="login", priority="medium", status="pending", customer_id=customers[0].id, module_id=login.id, created_at=_at(6, 16), first_response_at=_at(6, 17)),
        Ticket(title="订单状态长时间未更新", body_redacted="订单状态停留在处理中，未出现新的状态变化。", category="order", priority="medium", status="open", customer_id=customers[1].id, module_id=order.id, created_at=_at(8, 7)),
        Ticket(title="退款进度查询失败", body_redacted="退款进度页返回暂时不可用提示。", category="refund", priority="low", status="resolved", customer_id=customers[2].id, module_id=order.id, created_at=_at(2, 9), first_response_at=_at(2, 10), resolved_at=_at(2, 12)),
    ]
    session.add_all(tickets)
    session.flush()
    session.add_all(
        [
            TicketEvent(ticket_id=tickets[0].id, event_type="created", occurred_at=_at(8, 9), actor_group="customer"),
            TicketEvent(ticket_id=tickets[2].id, event_type="responded", occurred_at=_at(7, 15, 10), actor_group="support"),
            TicketEvent(ticket_id=tickets[3].id, event_type="resolved", occurred_at=_at(3, 14), actor_group="support"),
            TicketEvent(ticket_id=tickets[4].id, event_type="created", occurred_at=_at(8, 8), actor_group="customer"),
        ]
    )
    session.add_all(
        [
            ServiceKnowledge(source_type="known_issue", title="支付回调延迟排查", body_redacted="核对回调队列积压和订单状态同步任务。", category="payment", module_id=payment.id, version="v1"),
            ServiceKnowledge(source_type="sop", title="登录失败标准处理", body_redacted="确认验证码状态、会话有效期和异常日志编号。", category="login", module_id=login.id, version="v1"),
            ServiceKnowledge(source_type="faq", title="订单状态处理说明", body_redacted="订单处理中时先确认状态更新时间和下游同步。", category="order", module_id=order.id, version="v1"),
        ]
    )
    session.commit()
    return _summary(session, created=True)
