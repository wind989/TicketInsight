import asyncio

from httpx import ASGITransport, AsyncClient

from app.main import app


def test_health() -> None:
    async def request_health() -> tuple[int, dict[str, str]]:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.get("/health")
        return response.status_code, response.json()

    status_code, body = asyncio.run(request_health())

    assert status_code == 200
    assert body == {"status": "ok", "service": "ticketinsight"}
