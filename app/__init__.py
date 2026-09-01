from fastapi import FastAPI

from app.configuration.events import startup_events, shutdown_events
from app.configuration.server import Server


def create_app() -> FastAPI:
    return Server(
        start_up_events=startup_events,
        shut_down_events=shutdown_events,
    ).get_app()

application = create_app()
