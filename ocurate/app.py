import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from ocurate.config import load_settings
from ocurate.log_setup import configure_logging, log_event
from ocurate.passages.passage import UnknownPassageError
from ocurate.passages.passage_store import StoredPassageError, get_passage, list_passages
from ocurate.schemas.passage import PassageSummary, passage_summary
from ocurate.api.sessions_api import router as sessions_router
from ocurate.sessions.tokens import build_token_store
from ocurate.api.ws_api import router as ws_router

logger = logging.getLogger(__name__)


def create_app(settings=None):

    settings = settings or load_settings()

    configure_logging(settings.log_level)

    # The engine connects lazily, so the app starts without a reachable database.
    # pool_pre_ping replaces connections MySQL has closed after wait_timeout.
    engine = create_engine(settings.database_url, pool_pre_ping=True) if settings.database_url else None

    @asynccontextmanager
    async def lifespan(app):

        yield

        if engine is not None:
            engine.dispose()

    app = FastAPI(title="Ocurate gaze-analysis service", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.tokens = build_token_store(settings)
    # Called with each finished Session's Outcome; the signed result callback replaces it.
    app.state.on_session_finished = lambda outcome: None

    def require_engine():

        if engine is None:
            raise HTTPException(status_code=503, detail="passage database not configured")

        return engine

    def database_unavailable(error):

        log_event(logger, "passage_database_error", level=logging.ERROR, error=type(error).__name__)

        return HTTPException(status_code=503, detail="passage database unavailable")

    @app.get("/health")
    def health():

        return {"status": "ok"}

    @app.get("/passages", response_model=list[PassageSummary])
    def passages():

        try:
            return list_passages(require_engine())
        except SQLAlchemyError as error:
            raise database_unavailable(error) from error

    @app.get("/passages/{passage_id}", response_model=PassageSummary)
    def passage(passage_id: str):

        try:
            return passage_summary(passage_id, get_passage(require_engine(), passage_id))
        except UnknownPassageError:
            raise HTTPException(status_code=404, detail="unknown passage id")
        except StoredPassageError as error:
            log_event(logger, "passage_invalid", level=logging.ERROR, passage_id=passage_id, reason=error)
            raise HTTPException(status_code=500, detail="stored passage is invalid")
        except SQLAlchemyError as error:
            raise database_unavailable(error) from error

    app.include_router(sessions_router)
    app.include_router(ws_router)

    return app


app = create_app()
