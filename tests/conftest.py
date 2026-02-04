"""Centralized pytest fixtures for Aeolus tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest
import socketio
from cryptography.fernet import Fernet

TEST_FERNET_KEY = Fernet.generate_key().decode("utf-8")


@pytest.fixture
def mock_sio():
    """Mock socketio.AsyncServer for testing socket events."""
    sio = MagicMock(spec=socketio.AsyncServer)
    sio.save_session = AsyncMock()
    sio.get_session = AsyncMock(return_value={"userId": 123, "roleId": 456, "chatSessionId": 789})
    sio.enter_room = AsyncMock()
    sio.leave_room = AsyncMock()
    sio.emit = AsyncMock()
    sio.on = MagicMock()
    return sio


@pytest.fixture
def test_fernet_key():
    """Consistent Fernet key for testing."""
    return TEST_FERNET_KEY


def create_test_token(user_id: int, role_id: int, session_id: int, fernet_key: str = TEST_FERNET_KEY) -> str:
    """Create a valid Fernet-encrypted token for testing."""
    f = Fernet(fernet_key)
    token_data = f"{user_id}:{role_id}:{session_id}"
    return f.encrypt(token_data.encode()).decode("utf-8")
