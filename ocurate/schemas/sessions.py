from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class CreateSessionRequest(BaseModel):
    """Body of POST /sessions, sent by the web server."""

    model_config = ConfigDict(extra="forbid", strict=True)

    passage_id: Annotated[str, Field(min_length=1, max_length=200)]


class CreateSessionResponse(BaseModel):
    """`token` goes to the browser for its `hello` message. `expires_in` is
    in seconds, so the web server does not depend on our clock."""

    session_id: str
    passage_id: str
    token: str
    expires_in: int
