import socketio
from aiohttp import web
from aiohttp_cors import ResourceOptions
from aiohttp_cors import setup as cors_setup

from api.routes import setup_routes
from events.socket import setup_socket_events
from logger import aeolus_logger
from redis_client import redis_client
from settings import load_settings


def _build_cors_allowed_origins(cors_origin: str):
    if cors_origin == "*":
        return "*"
    return [cors_origin]


def _build_cors_config(cors_origin: str):
    if cors_origin == "*":
        return {
            "*": ResourceOptions(allow_credentials=True, expose_headers="*", allow_headers="*", allow_methods="*")
        }
    return {
        cors_origin: ResourceOptions(allow_credentials=True, expose_headers="*", allow_headers="*", allow_methods="*")
    }


def _build_socket_server(cors_allowed_origins, socketio_redis_url: str | None):
    manager = None
    if socketio_redis_url:
        manager = socketio.AsyncRedisManager(socketio_redis_url)
    return socketio.AsyncServer(
        async_mode="aiohttp",
        cors_allowed_origins=cors_allowed_origins,
        transports=["websocket"],
        logger=True,
        engineio_logger=True,
        client_manager=manager,
    )


def create_app() -> web.Application:
    settings = load_settings()
    cors_allowed_origins = _build_cors_allowed_origins(settings.cors_origin)
    sio = _build_socket_server(cors_allowed_origins, settings.socketio_redis_url)
    app = web.Application()
    app["settings"] = settings

    cors = cors_setup(app, defaults=_build_cors_config(settings.cors_origin))
    sio.attach(app)

    setup_socket_events(sio, settings.auth_token_prefix)
    setup_routes(app, sio, settings.server_secret)

    for route in list(app.router.routes()):
        try:
            cors.add(route)
        except ValueError:
            pass

    async def on_startup(app):
        await redis_client.connect()
        aeolus_logger.info(f"Socket server running on port {app['settings'].port}")
        aeolus_logger.info(f"Redis connected: {redis_client.redis_url}")
        aeolus_logger.info(f"CORS origin: {app['settings'].cors_origin}")
        aeolus_logger.info(f"Auth token prefix: {app['settings'].auth_token_prefix}")
        if app["settings"].socketio_redis_url:
            aeolus_logger.info("Socket.IO Redis manager enabled")

    async def on_shutdown(app):
        await redis_client.disconnect()

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    return app


app = create_app()


if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=app["settings"].port)
