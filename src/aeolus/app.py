import logging

import socketio
from aiohttp import web
from aiohttp_cors import ResourceOptions
from aiohttp_cors import setup as cors_setup

from src.aeolus.api import setup_routes
from src.aeolus.events import setup_socket_events
from src.aeolus.settings import Settings, load_settings

logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
logger = logging.getLogger("aeolus")

settings_key = web.AppKey("settings", Settings)


def _build_cors_allowed_origins(cors_origin: str):
    if cors_origin == "*":
        return "*"
    return [cors_origin]


def _build_cors_config(cors_origin: str):
    opts = ResourceOptions(
        allow_credentials=True,
        expose_headers="*",
        allow_headers="*",
        allow_methods="*",
    )
    if cors_origin == "*":
        return {"*": opts}
    return {cors_origin: opts}


def _build_socket_server(settings: Settings, cors_allowed_origins):
    manager = None
    if settings.socketio_redis_url:
        manager = socketio.AsyncRedisManager(settings.socketio_redis_url)
    else:
        logger.warning("SOCKETIO_REDIS_URL not set - multi-worker mode will not work correctly")
    return socketio.AsyncServer(
        async_mode="aiohttp",
        cors_allowed_origins=cors_allowed_origins,
        transports=["websocket"],
        client_manager=manager,
        logger=settings.socketio_logger,
        engineio_logger=settings.engineio_logger,
    )


def create_app(settings: Settings | None = None) -> web.Application:
    if settings is None:
        settings = load_settings()

    cors_allowed_origins = _build_cors_allowed_origins(settings.cors_origin)
    sio = _build_socket_server(settings, cors_allowed_origins)
    app = web.Application()
    app[settings_key] = settings

    cors = cors_setup(app, defaults=_build_cors_config(settings.cors_origin))
    sio.attach(app)

    setup_socket_events(sio, settings.fernet_key)
    setup_routes(app, sio, settings.server_secret)

    for route in list(app.router.routes()):
        try:
            cors.add(route)
        except ValueError:
            pass

    async def on_startup(app: web.Application) -> None:
        logger.info(f"Socket server running on port {app['settings'].port}")
        logger.info(f"CORS origin: {app['settings'].cors_origin}")
        logger.info(f"Fernet auth: {'configured' if app['settings'].fernet_key else 'NOT configured'}")
        if app[settings_key].socketio_redis_url:
            logger.info("Socket.IO Redis manager enabled")

    app.on_startup.append(on_startup)

    return app


if __name__ == "__main__":
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=app[settings_key].port)
