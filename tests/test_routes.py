from unittest.mock import AsyncMock

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.routes import setup_routes


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


class TestReadReceiptRoute(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        self.mock_sio = AsyncMock()
        setup_routes(app, socket_server=self.mock_sio, server_secret="test-secret-key")
        return app

    async def test_missing_auth_header(self):
        resp = await self.client.request(
            "POST",
            "/chat/read-receipt",
            json={"channelId": "chat_1", "messageId": 17},
        )
        assert resp.status == 401
        data = await resp.json()
        assert data["error"] == "Unauthorized"

    async def test_invalid_secret(self):
        headers = {"Authorization": "Bearer wrong-secret"}
        resp = await self.client.request(
            "POST",
            "/chat/read-receipt",
            json={"channelId": "chat_1", "messageId": 17},
            headers=headers,
        )
        assert resp.status == 401
        data = await resp.json()
        assert data["error"] == "Unauthorized"

    async def test_invalid_json(self):
        headers = {"Authorization": "Bearer test-secret-key"}
        resp = await self.client.request(
            "POST",
            "/chat/read-receipt",
            data="not json",
            headers=headers,
        )
        assert resp.status == 400
        data = await resp.json()
        assert data["error"] == "Invalid JSON"

    async def test_missing_fields(self):
        headers = {"Authorization": "Bearer test-secret-key"}
        resp = await self.client.request(
            "POST",
            "/chat/read-receipt",
            json={"channelId": "chat_1"},
            headers=headers,
        )
        assert resp.status == 400
        data = await resp.json()
        assert data["error"] == "channelId and messageId are required"

    async def test_success(self):
        headers = {"Authorization": "Bearer test-secret-key"}
        payload = {
            "channelId": "chat_1",
            "messageId": 42,
            "readerId": 9,
            "readAt": "2026-01-06T12:00:00Z",
            "complete": True,
            "readers": [{"role_id": 9, "name": "Tester", "read_at": "2026-01-06T12:00:00Z"}],
        }
        resp = await self.client.request("POST", "/chat/read-receipt", json=payload, headers=headers)
        assert resp.status == 200
        data = await resp.json()
        assert data["success"] is True
        self.mock_sio.emit.assert_awaited_once_with(
            "message:read",
            {
                "channelId": "chat_1",
                "messageId": 42,
                "readerId": 9,
                "readAt": "2026-01-06T12:00:00Z",
                "complete": True,
                "readers": [{"role_id": 9, "name": "Tester", "read_at": "2026-01-06T12:00:00Z"}],
            },
            room="chat_1",
        )


class TestChatMessageRoute(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        self.mock_sio = AsyncMock()
        setup_routes(app, socket_server=self.mock_sio, server_secret="test-secret-key")
        return app

    async def test_missing_auth_header(self):
        resp = await self.client.request(
            "POST",
            "/chat/message",
            json={"channelId": "chat_1", "senderId": 1, "content": "Hello", "messageId": 5},
        )
        assert resp.status == 401
        data = await resp.json()
        assert data["error"] == "Unauthorized"

    async def test_invalid_json(self):
        headers = {"Authorization": "Bearer test-secret-key"}
        resp = await self.client.request(
            "POST",
            "/chat/message",
            data="not json",
            headers=headers,
        )
        assert resp.status == 400
        data = await resp.json()
        assert data["error"] == "Invalid JSON"

    async def test_missing_fields(self):
        headers = {"Authorization": "Bearer test-secret-key"}
        resp = await self.client.request(
            "POST",
            "/chat/message",
            json={"channelId": "chat_1", "content": "Hi"},
            headers=headers,
        )
        assert resp.status == 400
        data = await resp.json()
        assert data["error"] == "channelId, senderId, content, and messageId are required"

    async def test_success(self):
        headers = {"Authorization": "Bearer test-secret-key"}
        payload = {
            "channelId": "chat_1",
            "senderId": 7,
            "content": "Hi there",
            "messageId": 55,
            "timestamp": "2026-01-06T12:00:00Z",
            "senderName": "Tester",
        }
        resp = await self.client.request("POST", "/chat/message", json=payload, headers=headers)
        assert resp.status == 200
        data = await resp.json()
        assert data["success"] is True
        self.mock_sio.emit.assert_awaited_once_with(
            "message:received",
            {
                "channelId": "chat_1",
                "senderId": 7,
                "content": "Hi there",
                "messageId": 55,
                "timestamp": "2026-01-06T12:00:00Z",
                "senderName": "Tester",
            },
            room="chat_1",
        )
