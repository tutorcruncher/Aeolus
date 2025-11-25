import socketio
from aiohttp import web

from logger import aeolus_logger
from main.api.routes import setup_routes
from main.config import config
from main.events.socket import setup_socket_events
from main.redis import redis_client


def _setup_app():
    if config.cors_origin == "*":
        cors_allowed_origins = "*"
    else:
        cors_allowed_origins = [*config.cors_origin.split(",")]

    sio = socketio.AsyncServer(
        async_mode="aiohttp", cors_allowed_origins=cors_allowed_origins, logger=True, engineio_logger=True
    )
    setup_socket_events(sio, config.auth_token_prefix)
    app = web.Application()
    setup_routes(app)

    return app


async def on_startup(app):
    await redis_client.connect()
    aeolus_logger.info(f"Socket server running on port {config.port}")
    aeolus_logger.info(f"Redis connected: {redis_client.redis_url}")
    aeolus_logger.info(f"CORS origin: {config.cors_origin}")


async def on_shutdown(app):
    await redis_client.disconnect()


if __name__ == "__main__":
    app = _setup_app()

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    web.run_app(app, host="0.0.0.0", port=config.port)
