import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def env(key: str, cast: type):
    if value := os.getenv(str.upper(key)):
        return cast(value)


@dataclass(frozen=True)
class Config:
    auth_token_prefix: str
    cors_origin: str
    port: int


config = Config(
    auth_token_prefix=env("auth_token_prefix", str),
    cors_origin=env("cors_origin", str),
    port=env("port", int),
)
