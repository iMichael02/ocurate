from fastapi import FastAPI, HTTPException

from config import Settings, load_settings
from log_setup import configure_logging
from passage import PASSAGES, UnknownPassageError, get_passage
from schemas.passage import PassageSummary, passage_summary
from sessions_api import router as sessions_router
from tokens import build_token_store


def create_app(settings=None):

    settings = settings or load_settings()

    configure_logging(settings.log_level)

    app = FastAPI(title="Ocurate gaze-analysis service")
    app.state.settings = settings
    # T8 checks WebSocket tokens with app.state.tokens.verify_and_consume_token.
    app.state.tokens = build_token_store(settings)

    @app.get("/health")
    def health():

        return {"status": "ok"}

    @app.get("/passages", response_model=list[PassageSummary])
    def passages():

        return [passage_summary(passage_id, passage) for passage_id, passage in PASSAGES.items()]

    @app.get("/passages/{passage_id}", response_model=PassageSummary)
    def passage(passage_id: str):

        try:
            return passage_summary(passage_id, get_passage(passage_id))
        except UnknownPassageError:
            raise HTTPException(status_code=404, detail="unknown passage id")

    app.include_router(sessions_router)

    return app


app = create_app()
