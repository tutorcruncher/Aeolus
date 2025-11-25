import os

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

# Set SERVER_SECRET before importing api.routes
os.environ["SERVER_SECRET"] = "test-secret-key"

from main.api import setup_routes


class TestHealthRoute(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        setup_routes(app)
        return app

    async def test_health_returns_ok(self):
        resp = await self.client.request("GET", "/health")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"
        assert "timestamp" in data
        assert data["timestamp"].endswith("Z")


class TestStatusRoute(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        setup_routes(app)
        return app

    async def test_status_returns_running(self):
        resp = await self.client.request("GET", "/status")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "running"
        assert "uptime" in data
        assert isinstance(data["uptime"], (int, float))


class TestInitChannelRoute(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        setup_routes(app)
        return app

    async def test_init_channel_missing_auth_header(self):
        resp = await self.client.request("POST", "/init-channel", json={"channelId": "test-channel"})
        assert resp.status == 401
        data = await resp.json()
        assert data["error"] == "Unauthorized"

    async def test_init_channel_invalid_auth_header_format(self):
        headers = {"Authorization": "InvalidFormat"}
        resp = await self.client.request("POST", "/init-channel", json={"channelId": "test-channel"}, headers=headers)
        assert resp.status == 401
        data = await resp.json()
        assert data["error"] == "Unauthorized"

    async def test_init_channel_invalid_secret(self):
        headers = {"Authorization": "Bearer wrong-secret"}
        resp = await self.client.request("POST", "/init-channel", json={"channelId": "test-channel"}, headers=headers)
        assert resp.status == 401
        data = await resp.json()
        assert data["error"] == "Unauthorized"

    async def test_init_channel_missing_channel_id(self):
        headers = {"Authorization": "Bearer test-secret-key"}
        resp = await self.client.request("POST", "/init-channel", json={}, headers=headers)
        assert resp.status == 400
        data = await resp.json()
        assert data["error"] == "channelId is required"

    async def test_init_channel_invalid_json(self):
        headers = {"Authorization": "Bearer test-secret-key"}
        resp = await self.client.request("POST", "/init-channel", data="invalid json", headers=headers)
        assert resp.status == 400
        data = await resp.json()
        assert data["error"] == "Invalid JSON"

    async def test_init_channel_success(self):
        headers = {"Authorization": "Bearer test-secret-key"}
        resp = await self.client.request(
            "POST", "/init-channel", json={"channelId": "test-channel", "metadata": {"key": "value"}}, headers=headers
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["success"] is True
        assert data["channelId"] == "test-channel"

    async def test_init_channel_success_without_metadata(self):
        headers = {"Authorization": "Bearer test-secret-key"}
        resp = await self.client.request("POST", "/init-channel", json={"channelId": "test-channel"}, headers=headers)
        assert resp.status == 200
        data = await resp.json()
        assert data["success"] is True
        assert data["channelId"] == "test-channel"
