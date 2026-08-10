"""The optional model adapter remains locally configured and time-bounded without making network calls."""

from __future__ import annotations

import pytest

from app.core.config import get_llm_timeout_seconds
from app.services.llm_advisor import OpenAICompatibleAdvisor


def test_llm_timeout_reads_a_bounded_local_setting(monkeypatch):
    monkeypatch.setenv("TICKETINSIGHT_LLM_TIMEOUT_SECONDS", "17.5")

    assert get_llm_timeout_seconds() == 17.5


def test_llm_adapter_rejects_unbounded_timeout_without_contacting_provider():
    with pytest.raises(ValueError):
        OpenAICompatibleAdvisor(endpoint="https://example.invalid", api_key="local-test-key", model="fake", timeout_seconds=0)

    advisor = OpenAICompatibleAdvisor(endpoint="https://example.invalid", api_key="local-test-key", model="fake", timeout_seconds=12)
    try:
        assert advisor.timeout_seconds == 12
        assert advisor._http_client.timeout.connect == 5
        assert advisor._http_client.timeout.read == 12
        assert advisor._http_client.follow_redirects is False
    finally:
        advisor._http_client.close()
