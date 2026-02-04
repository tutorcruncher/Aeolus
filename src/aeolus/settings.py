import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _env_int(var_name: str, default: int) -> int:
    value = os.getenv(var_name)
    return int(value) if value is not None else default


def _env_bool(var_name: str, default: bool = False) -> bool:
    value = os.getenv(var_name)
    if value is None:
        return default
    return value.upper() == "TRUE"


@dataclass(frozen=True, slots=True)
class Settings:
    port: int
    cors_origin: str
    fernet_key: str | None
    server_secret: str | None
    socketio_redis_url: str | None
    debug: bool = False
    socketio_logger: bool = True
    engineio_logger: bool = True


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        port=_env_int("PORT", 3000),
        cors_origin=os.getenv("CORS_ORIGIN", "*"),
        fernet_key=os.getenv("TC_CHAT_FERNET_KEY"),
        server_secret=os.getenv("SERVER_SECRET"),
        socketio_redis_url=os.getenv("SOCKETIO_REDIS_URL"),
        debug=_env_bool("DEBUG", False),
        socketio_logger=_env_bool("SOCKETIO_LOGGER", True),
        engineio_logger=_env_bool("ENGINEIO_LOGGER", True),
    )
