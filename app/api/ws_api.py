import asyncio
import logging

from fastapi import APIRouter, WebSocket
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.exc import SQLAlchemyError
from starlette.websockets import WebSocketDisconnect

from app.log_setup import log_event
from app.passages.passage_store import StoredPassageError, get_passage
from app.schemas import protocol
from app.sessions.session_manager import Authenticated, PassageUnavailable, Session

logger = logging.getLogger(__name__)

router = APIRouter()


def make_authenticator(app):
    """Checks a Session token and loads the Passage it was issued for."""

    def authenticate(token):

        grant = app.state.tokens.verify_and_consume_token(token)

        if app.state.engine is None:
            raise PassageUnavailable()

        try:
            passage = get_passage(app.state.engine, grant.passage_id)
        except (SQLAlchemyError, StoredPassageError, KeyError):
            raise PassageUnavailable() from None

        return Authenticated(grant.session_id, grant.passage_id, passage)

    return authenticate


async def send_reply(websocket, reply):
    """Sends the reply's messages and closes the socket if it says so.
    Returns True if the socket was closed."""

    for message in reply.messages:
        await websocket.send_text(protocol.serialize(message))

    if reply.close_code is not None:
        await websocket.close(reply.close_code)
        return True

    return False


@router.websocket("/ws")
async def session_socket(websocket: WebSocket):

    app = websocket.app
    settings = app.state.settings
    session = Session(settings, make_authenticator(app))

    await websocket.accept()

    try:
        while True:
            try:
                event = await asyncio.wait_for(websocket.receive(), settings.session_inactivity_seconds)
            except asyncio.TimeoutError:
                reply = session.timeout()
            else:
                if event["type"] == "websocket.disconnect":
                    break
                # The handshake looks up the Passage in the database, so every
                # message is handled off the event loop.
                reply = await run_in_threadpool(session.receive, event.get("text"))

            if await send_reply(websocket, reply):
                break
    except WebSocketDisconnect:
        pass
    finally:
        session.socket_closed()

        if session.outcome is not None:
            # T10 hooks the signed result callback to the web server in here.
            app.state.on_session_finished(session.outcome)
