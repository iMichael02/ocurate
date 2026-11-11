import hmac
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError

from app.log_setup import log_event
from app.passages.passage import UnknownPassageError
from app.passages.passage_store import StoredPassageError, get_passage
from app.schemas.sessions import CreateSessionRequest, CreateSessionResponse
from app.sessions.tokens import TooManySessions

logger = logging.getLogger(__name__)

router = APIRouter()


def require_api_key(request: Request, x_api_key: Optional[str] = Header(default=None)):
    """Runs as a dependency so the key is checked before the body is validated."""

    expected = request.app.state.settings.api_key

    # Same 401 for a missing key, a wrong key and an unset API key, so a
    # caller learns nothing about how the service is configured.
    given = (x_api_key or "").encode("utf-8")
    if not expected or not hmac.compare_digest(given, expected.encode("utf-8")):
        log_event(logger, "session_create_refused", logging.WARNING,
                  reason="unauthorized" if expected else "api_key_unset")
        raise HTTPException(status_code=401, detail="unauthorized")

    # Only a caller with the key learns that the token secret is missing.
    if not request.app.state.tokens.configured:
        log_event(logger, "session_create_refused", logging.WARNING, reason="token_secret_unset")
        raise HTTPException(status_code=503, detail="session creation is not configured")


@router.post("/sessions", status_code=201, response_model=CreateSessionResponse,
             dependencies=[Depends(require_api_key)])
def create_session(body: CreateSessionRequest, request: Request):

    engine = request.app.state.engine

    if engine is None:
        raise HTTPException(status_code=503, detail="passage database not configured")

    try:
        get_passage(engine, body.passage_id)
    except UnknownPassageError:
        raise HTTPException(status_code=404, detail="unknown passage id")
    except StoredPassageError:
        raise HTTPException(status_code=500, detail="stored passage is invalid")
    except SQLAlchemyError as error:
        log_event(logger, "passage_database_error", logging.ERROR, error=type(error).__name__)
        raise HTTPException(status_code=503, detail="passage database unavailable") from error

    tokens = request.app.state.tokens

    try:
        issued = tokens.create_session(body.passage_id)
    except TooManySessions:
        log_event(logger, "session_create_refused", logging.WARNING, reason="too_many_pending")
        raise HTTPException(status_code=503, detail="too many pending sessions")

    log_event(logger, "session_created", session_id=issued.session_id, passage_id=body.passage_id)

    return CreateSessionResponse(
        session_id=issued.session_id,
        passage_id=body.passage_id,
        token=issued.token,
        expires_in=tokens.ttl_seconds,
    )
