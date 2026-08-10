"""Isolated HTTPX client and SQLite database for API tests."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx
import pytest


os.environ["TICKETINSIGHT_DATABASE_URL"] = "sqlite:///./test-bootstrap.db"
# Tests must never inherit a developer's paid-model, vector-service, or read-only database settings from .env.
# Empty values win over python-dotenv because it loads with override=False, and production construction fails closed.
for _runtime_only_variable in (
    "TICKETINSIGHT_READONLY_DATABASE_URL",
    "TICKETINSIGHT_QDRANT_URL",
    "TICKETINSIGHT_DEEPSEEK_API_KEY",
    "TICKETINSIGHT_DEEPSEEK_BASE_URL",
    "TICKETINSIGHT_DEEPSEEK_MODEL",
):
    os.environ[_runtime_only_variable] = ""

from app.core import database  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402


class ASGISyncClient:
    """Small synchronous test facade built on the supported HTTPX ASGI transport."""

    def request(self, method: str, url: str, **kwargs):
        async def send():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
                return await async_client.request(method, url, **kwargs)

        return asyncio.run(send())

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)

    def patch(self, url: str, **kwargs):
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs):
        return self.request("DELETE", url, **kwargs)


@pytest.fixture
def client(tmp_path: Path):
    database.configure_database(f"sqlite:///{(tmp_path / 'ticketinsight-test.db').as_posix()}")
    Base.metadata.create_all(bind=database.engine)
    get_settings.cache_clear()
    yield ASGISyncClient()
    Base.metadata.drop_all(bind=database.engine)
    database.engine.dispose()
    get_settings.cache_clear()
