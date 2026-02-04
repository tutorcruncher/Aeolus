"""Test data factories for Aeolus."""

from dataclasses import dataclass

from cryptography.fernet import Fernet

TEST_FERNET_KEY = Fernet.generate_key().decode("utf-8")


@dataclass
class MockSession:
    """Mock session data for testing."""

    user_id: int = 123
    role_id: int = 456
    chat_session_id: int = 789

    def to_dict(self) -> dict:
        return {
            "userId": self.user_id,
            "roleId": self.role_id,
            "chatSessionId": self.chat_session_id,
        }


def create_auth_token(user_id: int, role_id: int, session_id: int, key: str = TEST_FERNET_KEY) -> str:
    """Create a Fernet-encrypted auth token."""
    f = Fernet(key)
    return f.encrypt(f"{user_id}:{role_id}:{session_id}".encode()).decode("utf-8")


def create_message_payload(channel_id: str, sender_id: int, content: str, message_id: str) -> dict:
    """Create a message payload for testing."""
    return {
        "channelId": channel_id,
        "senderId": sender_id,
        "content": content,
        "messageId": message_id,
    }


def create_read_receipt_payload(channel_id: str, message_id: str, complete: bool = False) -> dict:
    """Create a read receipt payload for testing."""
    return {
        "channelId": channel_id,
        "messageId": message_id,
        "complete": complete,
    }
