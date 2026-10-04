from fastapi import FastAPI

from config import Settings, load_settings
from log_setup import configure_logging


def create_app(settings=None):

    settings = settings or load_settings()

    configure_logging(settings.log_level)

    app = FastAPI(title="Ocurate gaze-analysis service")
    app.state.settings = settings

    @app.get("/health")
    def health():

        return {"status": "ok"}

    return app


app = create_app()
