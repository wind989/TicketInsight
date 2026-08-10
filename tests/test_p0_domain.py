"""P0 HTTPX evidence for CRUD, synthetic data and de-identification boundaries."""

from __future__ import annotations


def test_seeded_synthetic_domain_can_be_filtered_and_reused(client):
    first_seed = client.post("/api/v1/demo/seed")
    assert first_seed.status_code == 200, first_seed.text
    assert first_seed.json() == {
        "created": True,
        "customers": 4,
        "product_modules": 3,
        "sla_policies": 4,
        "tickets": 8,
        "ticket_events": 4,
        "service_knowledge": 3,
    }

    second_seed = client.post("/api/v1/demo/seed")
    assert second_seed.status_code == 200
    assert second_seed.json()["created"] is False
    assert second_seed.json()["tickets"] == 8

    payments = client.get("/api/v1/tickets", params={"category": "payment", "limit": 20})
    assert payments.status_code == 200
    assert len(payments.json()) == 4
    assert all(item["category"] == "payment" for item in payments.json())

    knowledge = client.get("/api/v1/service-knowledge", params={"category": "login"})
    assert knowledge.status_code == 200
    assert knowledge.json()[0]["source_type"] == "sop"


def test_ready_reports_only_the_current_crud_runtime_scope(client):
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "scope": "p0_crud_runtime",
        "components": {"database": "ok", "analysis_runtime": "not_checked"},
    }


def test_crud_validates_links_and_rejects_clear_pii(client):
    customer = client.post("/api/v1/customers", json={"anonymous_id": "anon-Z999", "tier": "vip"})
    assert customer.status_code == 201, customer.text
    module = client.post(
        "/api/v1/product-modules",
        json={"name": "测试模块", "description": "用于隔离 API 验证的合成模块", "status": "active"},
    )
    assert module.status_code == 201, module.text
    policy = client.post(
        "/api/v1/sla-policies",
        json={"category": "login", "priority": "high", "response_minutes": 30, "resolution_minutes": 240},
    )
    assert policy.status_code == 201, policy.text

    ticket = client.post(
        "/api/v1/tickets",
        json={
            "title": "登录状态校验异常",
            "body_redacted": "登录后状态没有按预期保持。",
            "category": "login",
            "priority": "high",
            "customer_id": customer.json()["id"],
            "module_id": module.json()["id"],
            "created_at": "2026-08-09T10:00:00Z",
        },
    )
    assert ticket.status_code == 201, ticket.text
    ticket_id = ticket.json()["id"]

    event = client.post(
        f"/api/v1/tickets/{ticket_id}/events",
        json={"event_type": "responded", "occurred_at": "2026-08-09T10:10:00Z", "actor_group": "support"},
    )
    assert event.status_code == 201, event.text
    updated = client.patch(f"/api/v1/tickets/{ticket_id}", json={"status": "pending"})
    assert updated.status_code == 200
    assert updated.json()["status"] == "pending"

    blocked_delete = client.delete(f"/api/v1/tickets/{ticket_id}")
    assert blocked_delete.status_code == 409
    pii = client.post(
        "/api/v1/tickets",
        json={
            "title": "请联系 test@example.com",
            "body_redacted": "此工单不应被保存。",
            "category": "login",
            "priority": "low",
            "customer_id": customer.json()["id"],
            "module_id": module.json()["id"],
            "created_at": "2026-08-09T10:00:00Z",
        },
    )
    assert pii.status_code == 422


def test_analysis_endpoint_fails_closed_without_qdrant_model_and_readonly_configuration(client):
    response = client.post("/api/v1/analysis-runs", json={"question": "为什么支付类投诉增加？"})

    assert response.status_code == 503
    assert "拒绝降级到未知目标" in response.json()["detail"]
