import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    port: int
    cors_origin: str
    auth_token_prefix: str
    server_secret: str | None
    socketio_redis_url: str | None


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        port=int(os.getenv("PORT", "3000")),
        cors_origin=os.getenv("CORS_ORIGIN", "*"),
        auth_token_prefix=os.getenv("AUTH_TOKEN_PREFIX", "tc2:socket:auth"),
        server_secret=os.getenv("SERVER_SECRET"),
        socketio_redis_url=os.getenv("SOCKETIO_REDIS_URL"),
    )
