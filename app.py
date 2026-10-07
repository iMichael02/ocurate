from fastapi import FastAPI, HTTPException

from config import Settings, load_settings
from log_setup import configure_logging
from passage import UnknownPassageError, get_passage, list_passages, passage_summary


def create_app(settings=None):

    settings = settings or load_settings()

    configure_logging(settings.log_level)

    app = FastAPI(title="Ocurate gaze-analysis service")
    app.state.settings = settings

    @app.get("/health")
    def health():

        return {"status": "ok"}

    @app.get("/passages")
    def passages():

        return list_passages()

    @app.get("/passages/{passage_id}")
    def passage(passage_id: str):

        try:
            return passage_summary(passage_id, get_passage(passage_id))
        except UnknownPassageError:
            raise HTTPException(status_code=404, detail="unknown passage id")

    return app


app = create_app()
