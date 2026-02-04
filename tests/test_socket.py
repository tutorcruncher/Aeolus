"""Tests for Socket.IO event handlers."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from src.aeolus.events import SocketEventHandlers, validate_auth_token
from tests.conftest import TEST_FERNET_KEY, create_test_token


class TestValidateAuthToken:
    def test_validate_auth_token_success(self):
        token = create_test_token(123, 456, 789)
        result = validate_auth_token(token, TEST_FERNET_KEY)

        assert result is not None
        assert result["userId"] == 123
        assert result["roleId"] == 456
        assert result["chatSessionId"] == 789

    def test_validate_auth_token_invalid_token(self):
        result = validate_auth_token("invalid-token", TEST_FERNET_KEY)
        assert result is None

    def test_validate_auth_token_no_fernet_key(self):
        token = create_test_token(123, 456, 789)
        result = validate_auth_token(token, None)
        assert result is None

    def test_validate_auth_token_wrong_key(self):
        token = create_test_token(123, 456, 789)
        wrong_key = Fernet.generate_key().decode("utf-8")
        result = validate_auth_token(token, wrong_key)
        assert result is None

    def test_validate_auth_token_malformed_data(self):
        f = Fernet(TEST_FERNET_KEY)
        bad_token = f.encrypt(b"123:456").decode("utf-8")
        result = validate_auth_token(bad_token, TEST_FERNET_KEY)
        assert result is None

    def test_validate_auth_token_expired(self):
        token = create_test_token(123, 456, 789)
        with patch("time.time", return_value=time.time() + 90000):
            result = validate_auth_token(token, TEST_FERNET_KEY)
        assert result is None

    def test_validate_auth_token_general_exception(self):
        """Test that general exceptions during token validation return None."""
        f = Fernet(TEST_FERNET_KEY)
        bad_token = f.encrypt(b"not-a-number:456:789").decode("utf-8")
        result = validate_auth_token(bad_token, TEST_FERNET_KEY)
        assert result is None

    def test_validate_auth_token_empty_fernet_key(self):
        """Test that empty fernet key returns None."""
        token = create_test_token(123, 456, 789)
        result = validate_auth_token(token, "")
        assert result is None


class TestSocketEventHandlers:
    @pytest.fixture
    def mock_sio(self):
        sio = MagicMock()
        sio.save_session = AsyncMock()
        sio.get_session = AsyncMock(return_value={"userId": 123, "roleId": 456, "chatSessionId": 789})
        sio.enter_room = AsyncMock()
        sio.leave_room = AsyncMock()
        sio.emit = AsyncMock()
        return sio

    @pytest.fixture
    def handlers(self, mock_sio):
        return SocketEventHandlers(mock_sio, TEST_FERNET_KEY)

    @pytest.mark.asyncio
    async def test_connect_no_token(self, handlers):
        result = await handlers.connect("test-sid", {}, None)
        assert result is False

        result = await handlers.connect("test-sid", {}, {})
        assert result is False

    @pytest.mark.asyncio
    async def test_connect_invalid_token(self, handlers):
        result = await handlers.connect("test-sid", {}, {"token": "invalid-token"})
        assert result is False

    @pytest.mark.asyncio
    async def test_connect_valid_token(self, handlers, mock_sio):
        token = create_test_token(123, 456, 789)
        result = await handlers.connect("test-sid", {}, {"token": token})
        assert result is None  # None means connection accepted
        mock_sio.save_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_channel_join(self, handlers, mock_sio):
        mock_sio.get_session.return_value = {"userId": 123, "chatSessionId": 456}
        await handlers.channel_join("test-sid", {"channelId": "456"})

        mock_sio.enter_room.assert_called_once_with("test-sid", "456")
        assert mock_sio.emit.call_count == 2

    @pytest.mark.asyncio
    async def test_channel_join_unauthorized(self, handlers, mock_sio):
        mock_sio.get_session.return_value = {"userId": 123, "chatSessionId": 456}
        await handlers.channel_join("test-sid", {"channelId": "789"})

        mock_sio.enter_room.assert_not_called()
        mock_sio.emit.assert_called_once_with("error", {"message": "Unauthorized for this channel"}, to="test-sid")

    @pytest.mark.asyncio
    async def test_channel_leave(self, handlers, mock_sio):
        mock_sio.get_session.return_value = {"userId": 123}
        await handlers.channel_leave("test-sid", {"channelId": "channel123"})

        mock_sio.leave_room.assert_called_once_with("test-sid", "channel123")
        assert mock_sio.emit.call_count == 2

    @pytest.mark.asyncio
    async def test_message_send(self, handlers, mock_sio):
        mock_sio.get_session.return_value = {"userId": 123}
        await handlers.message_send("test-sid", {"channelId": "channel123", "content": "Hello"})

        mock_sio.emit.assert_called_once()
        call_args = mock_sio.emit.call_args
        assert call_args[0][0] == "message:received"
        assert call_args[0][1]["senderId"] == 123
        assert call_args[0][1]["channelId"] == "channel123"
        assert call_args[0][1]["content"] == "Hello"
        assert "timestamp" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_message_read(self, handlers, mock_sio):
        mock_sio.get_session.return_value = {"userId": 123}
        await handlers.message_read(
            "test-sid",
            {
                "channelId": "channel123",
                "messageId": "msg-1",
                "readAt": "2026-01-06T12:00:00Z",
                "complete": True,
                "readers": [{"role_id": 5, "name": "Tester", "read_at": "2026-01-06T12:00:00Z"}],
            },
        )

        mock_sio.emit.assert_called_with(
            "message:read",
            {
                "channelId": "channel123",
                "messageId": "msg-1",
                "readerId": 123,
                "readAt": "2026-01-06T12:00:00Z",
                "complete": True,
                "readers": [{"role_id": 5, "name": "Tester", "read_at": "2026-01-06T12:00:00Z"}],
            },
            room="channel123",
            skip_sid="test-sid",
        )

    @pytest.mark.asyncio
    async def test_disconnect_with_session(self, handlers, mock_sio):
        """Test disconnect handler when session exists."""
        mock_sio.get_session.return_value = {"userId": 123}
        await handlers.disconnect("test-sid")
        mock_sio.get_session.assert_called()

    @pytest.mark.asyncio
    async def test_disconnect_session_error(self, handlers, mock_sio):
        """Test disconnect handler when get_session raises KeyError (session not found)."""
        mock_sio.get_session.side_effect = KeyError("test-sid")
        # Should not raise
        await handlers.disconnect("test-sid")

    @pytest.mark.asyncio
    async def test_channel_join_no_channel_id(self, handlers, mock_sio):
        """Test channel_join returns error when channelId is missing."""
        await handlers.channel_join("test-sid", {})

        mock_sio.emit.assert_called_once_with("error", {"message": "channelId required"}, to="test-sid")
        mock_sio.enter_room.assert_not_called()

    @pytest.mark.asyncio
    async def test_channel_leave_no_channel_id(self, handlers, mock_sio):
        """Test channel_leave returns early when channelId is missing."""
        await handlers.channel_leave("test-sid", {})

        mock_sio.leave_room.assert_not_called()
        mock_sio.emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_message_send_missing_channel_id(self, handlers, mock_sio):
        """Test message_send returns error when channelId is missing."""
        await handlers.message_send("test-sid", {"content": "Hello"})

        mock_sio.emit.assert_called_once_with("error", {"message": "channelId and content required"}, to="test-sid")

    @pytest.mark.asyncio
    async def test_message_send_missing_content(self, handlers, mock_sio):
        """Test message_send returns error when content is missing."""
        await handlers.message_send("test-sid", {"channelId": "channel123"})

        mock_sio.emit.assert_called_once_with("error", {"message": "channelId and content required"}, to="test-sid")

    @pytest.mark.asyncio
    async def test_message_read_missing_channel_id(self, handlers, mock_sio):
        """Test message_read returns error when channelId is missing."""
        await handlers.message_read("test-sid", {"messageId": "msg-1"})

        mock_sio.emit.assert_called_once_with("error", {"message": "channelId and messageId required"}, to="test-sid")

    @pytest.mark.asyncio
    async def test_message_read_missing_message_id(self, handlers, mock_sio):
        """Test message_read returns error when messageId is missing."""
        await handlers.message_read("test-sid", {"channelId": "channel123"})

        mock_sio.emit.assert_called_once_with("error", {"message": "channelId and messageId required"}, to="test-sid")
