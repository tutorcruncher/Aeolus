"""Tests for HTTP API routes."""

from unittest.mock import AsyncMock

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from src.aeolus.api import setup_routes


class TestHealthRoute(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        setup_routes(app, socket_server=None, server_secret=None)
        return app

    async def test_health_returns_ok(self):
        r = await self.client.request("GET", "/health")
        assert r.status == 200
        data = await r.json()
        assert data["status"] == "ok"
        assert "timestamp" in data
        assert data["timestamp"].endswith("Z")


class TestStatusRoute(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        setup_routes(app, socket_server=None, server_secret=None)
        return app

    async def test_status_returns_running(self):
        r = await self.client.request("GET", "/status")
        assert r.status == 200
        data = await r.json()
        assert data["status"] == "running"
        assert "uptime" in data
        assert isinstance(data["uptime"], (int, float))


class TestServerSecretMissing(AioHTTPTestCase):
    """Tests for when SERVER_SECRET is not configured."""

    async def get_application(self):
        app = web.Application()
        setup_routes(app, socket_server=AsyncMock(), server_secret=None)
        return app

    async def test_read_receipt_server_secret_missing(self):
        """Test read_receipt returns 503 when SERVER_SECRET is not configured."""
        headers = {"Authorization": "Bearer any-token"}
        r = await self.client.request(
            "POST",
            "/chat/read-receipt",
            json={"channelId": "chat_1", "messageId": 17},
            headers=headers,
        )
        assert r.status == 503
        data = await r.json()
        assert data["error"] == "Server secret missing"

    async def test_chat_message_server_secret_missing(self):
        """Test chat_message returns 503 when SERVER_SECRET is not configured."""
        headers = {"Authorization": "Bearer any-token"}
        r = await self.client.request(
            "POST",
            "/chat/message",
            json={"channelId": "chat_1", "senderId": 1, "content": "Hello", "messageId": 5},
            headers=headers,
        )
        assert r.status == 503
        data = await r.json()
        assert data["error"] == "Server secret missing"


class TestSocketServerUnavailable(AioHTTPTestCase):
    """Tests for when socket server is not configured."""

    async def get_application(self):
        app = web.Application()
        setup_routes(app, socket_server=None, server_secret="test-secret-key")
        return app

    async def test_read_receipt_socket_server_unavailable(self):
        """Test read_receipt returns 503 when socket server is not available."""
        headers = {"Authorization": "Bearer test-secret-key"}
        r = await self.client.request(
            "POST",
            "/chat/read-receipt",
            json={"channelId": "chat_1", "messageId": 17},
            headers=headers,
        )
        assert r.status == 503
        data = await r.json()
        assert data["error"] == "Socket server unavailable"

    async def test_chat_message_socket_server_unavailable(self):
        """Test chat_message returns 503 when socket server is not available."""
        headers = {"Authorization": "Bearer test-secret-key"}
        r = await self.client.request(
            "POST",
            "/chat/message",
            json={"channelId": "chat_1", "senderId": 1, "content": "Hello", "messageId": 5},
            headers=headers,
        )
        assert r.status == 503
        data = await r.json()
        assert data["error"] == "Socket server unavailable"


class TestReadReceiptRoute(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        self.mock_sio = AsyncMock()
        setup_routes(app, socket_server=self.mock_sio, server_secret="test-secret-key")
        return app

    async def test_missing_auth_header(self):
        r = await self.client.request(
            "POST",
            "/chat/read-receipt",
            json={"channelId": "chat_1", "messageId": 17},
        )
        assert r.status == 401
        data = await r.json()
        assert data["error"] == "Unauthorized"

    async def test_invalid_secret(self):
        headers = {"Authorization": "Bearer wrong-secret"}
        r = await self.client.request(
            "POST",
            "/chat/read-receipt",
            json={"channelId": "chat_1", "messageId": 17},
            headers=headers,
        )
        assert r.status == 401
        data = await r.json()
        assert data["error"] == "Unauthorized"

    async def test_invalid_json(self):
        headers = {"Authorization": "Bearer test-secret-key"}
        r = await self.client.request(
            "POST",
            "/chat/read-receipt",
            data="not json",
            headers=headers,
        )
        assert r.status == 400
        data = await r.json()
        assert data["error"] == "Invalid JSON"

    async def test_missing_fields(self):
        headers = {"Authorization": "Bearer test-secret-key"}
        r = await self.client.request(
            "POST",
            "/chat/read-receipt",
            json={"channelId": "chat_1"},
            headers=headers,
        )
        assert r.status == 400
        data = await r.json()
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
        r = await self.client.request("POST", "/chat/read-receipt", json=payload, headers=headers)
        assert r.status == 200
        data = await r.json()
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

    async def test_minimal_payload_without_optional_fields(self):
        """Test read receipt with only required fields (no readerId, readAt, readers)."""
        headers = {"Authorization": "Bearer test-secret-key"}
        payload = {
            "channelId": "chat_1",
            "messageId": 42,
        }
        r = await self.client.request("POST", "/chat/read-receipt", json=payload, headers=headers)
        assert r.status == 200
        data = await r.json()
        assert data["success"] is True
        call_args = self.mock_sio.emit.call_args
        assert call_args[0][0] == "message:read"
        emit_payload = call_args[0][1]
        assert emit_payload["channelId"] == "chat_1"
        assert emit_payload["messageId"] == 42
        assert emit_payload["complete"] is False
        assert "readerId" not in emit_payload
        assert "readAt" not in emit_payload
        assert "readers" not in emit_payload

    async def test_readers_invalid_type(self):
        """Test that readers field is only included if it's a list."""
        headers = {"Authorization": "Bearer test-secret-key"}
        payload = {
            "channelId": "chat_1",
            "messageId": 42,
            "readers": "not-a-list",
        }
        r = await self.client.request("POST", "/chat/read-receipt", json=payload, headers=headers)
        assert r.status == 200
        call_args = self.mock_sio.emit.call_args
        emit_payload = call_args[0][1]
        assert "readers" not in emit_payload

    async def test_auth_header_malformed_no_bearer(self):
        """Test auth header without Bearer prefix."""
        headers = {"Authorization": "test-secret-key"}
        r = await self.client.request(
            "POST",
            "/chat/read-receipt",
            json={"channelId": "chat_1", "messageId": 17},
            headers=headers,
        )
        assert r.status == 401
        data = await r.json()
        assert data["error"] == "Unauthorized"


class TestChatMessageRoute(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        self.mock_sio = AsyncMock()
        setup_routes(app, socket_server=self.mock_sio, server_secret="test-secret-key")
        return app

    async def test_missing_auth_header(self):
        r = await self.client.request(
            "POST",
            "/chat/message",
            json={"channelId": "chat_1", "senderId": 1, "content": "Hello", "messageId": 5},
        )
        assert r.status == 401
        data = await r.json()
        assert data["error"] == "Unauthorized"

    async def test_invalid_json(self):
        headers = {"Authorization": "Bearer test-secret-key"}
        r = await self.client.request(
            "POST",
            "/chat/message",
            data="not json",
            headers=headers,
        )
        assert r.status == 400
        data = await r.json()
        assert data["error"] == "Invalid JSON"

    async def test_missing_fields(self):
        headers = {"Authorization": "Bearer test-secret-key"}
        r = await self.client.request(
            "POST",
            "/chat/message",
            json={"channelId": "chat_1", "content": "Hi"},
            headers=headers,
        )
        assert r.status == 400
        data = await r.json()
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
        r = await self.client.request("POST", "/chat/message", json=payload, headers=headers)
        assert r.status == 200
        data = await r.json()
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

    async def test_without_optional_sender_name(self):
        """Test chat message without senderName."""
        headers = {"Authorization": "Bearer test-secret-key"}
        payload = {
            "channelId": "chat_1",
            "senderId": 7,
            "content": "Hi there",
            "messageId": 55,
            "timestamp": "2026-01-06T12:00:00Z",
        }
        r = await self.client.request("POST", "/chat/message", json=payload, headers=headers)
        assert r.status == 200
        call_args = self.mock_sio.emit.call_args
        emit_payload = call_args[0][1]
        assert "senderName" not in emit_payload

    async def test_auto_generated_timestamp(self):
        """Test that timestamp is auto-generated when not provided."""
        headers = {"Authorization": "Bearer test-secret-key"}
        payload = {
            "channelId": "chat_1",
            "senderId": 7,
            "content": "Hi there",
            "messageId": 55,
        }
        r = await self.client.request("POST", "/chat/message", json=payload, headers=headers)
        assert r.status == 200
        call_args = self.mock_sio.emit.call_args
        emit_payload = call_args[0][1]
        assert "timestamp" in emit_payload
        assert emit_payload["timestamp"].endswith("Z")
