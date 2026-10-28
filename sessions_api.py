import hmac
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from log_setup import log_event
from passage import UnknownPassageError, get_passage
from schemas.sessions import CreateSessionRequest, CreateSessionResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def require_api_key(request: Request, x_api_key: Optional[str] = Header(default=None)):
    """Runs as a dependency so the key is checked before the body is validated."""

    expected = request.app.state.settings.api_key

    if not expected or not request.app.state.tokens.configured:
        log_event(logger, "session_create_refused", logging.WARNING, reason="not_configured")
        raise HTTPException(status_code=503, detail="session creation is not configured")

    # Same 401 for a missing and a wrong key, so a caller learns nothing.
    given = (x_api_key or "").encode("utf-8")
    if not hmac.compare_digest(given, expected.encode("utf-8")):
        log_event(logger, "session_create_refused", logging.WARNING, reason="unauthorized")
        raise HTTPException(status_code=401, detail="unauthorized")


@router.post("/sessions", status_code=201, response_model=CreateSessionResponse,
             dependencies=[Depends(require_api_key)])
def create_session(body: CreateSessionRequest, request: Request):

    try:
        get_passage(body.passage_id)
    except UnknownPassageError:
        raise HTTPException(status_code=404, detail="unknown passage id")

    tokens = request.app.state.tokens
    issued = tokens.create_session(body.passage_id)

    log_event(logger, "session_created", session_id=issued.session_id, passage_id=body.passage_id)

    return CreateSessionResponse(
        session_id=issued.session_id,
        passage_id=body.passage_id,
        token=issued.token,
        expires_in=tokens.ttl_seconds,
    )
