from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine

from config import Settings, load_settings
from log_setup import configure_logging
from passage import UnknownPassageError, passage_summary
from passage_store import get_passage, list_passages


def create_app(settings=None):

    settings = settings or load_settings()

    configure_logging(settings.log_level)

    app = FastAPI(title="Ocurate gaze-analysis service")
    app.state.settings = settings

    # The engine connects lazily, so the app starts without a reachable database.
    # pool_pre_ping replaces connections MySQL has closed after wait_timeout.
    engine = create_engine(settings.database_url, pool_pre_ping=True) if settings.database_url else None
    app.state.engine = engine

    def require_engine():

        if engine is None:
            raise HTTPException(status_code=503, detail="passage database not configured")

        return engine

    @app.get("/health")
    def health():

        return {"status": "ok"}

    @app.get("/passages")
    def passages():

        return list_passages(require_engine())

    @app.get("/passages/{passage_id}")
    def passage(passage_id: str):

        try:
            return passage_summary(passage_id, get_passage(require_engine(), passage_id))
        except UnknownPassageError:
            raise HTTPException(status_code=404, detail="unknown passage id")

    return app


app = create_app()
