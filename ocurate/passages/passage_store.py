import logging

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from ocurate.config import load_settings
from ocurate.log_setup import log_event
from ocurate.passages.passage import Passage, UnknownPassageError, build_default_passage
from ocurate.schemas.passage import passage_summary

logger = logging.getLogger(__name__)

# One row per Passage. `text_lines` holds the plain-text rows joined with "\n";
# Passage lines are lowercase letters and spaces only, so the newline is
# unambiguous. (`lines` itself is a reserved word in MySQL.)
CREATE_PASSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS passages (
    id VARCHAR(64) PRIMARY KEY,
    text_lines TEXT NOT NULL
)
"""

DEFAULT_PASSAGE_ID = "default"


class StoredPassageError(ValueError):
    """A row in the passages table is not a valid Passage."""

    def __init__(self, passage_id, reason):

        self.passage_id = passage_id
        super().__init__(f"stored passage {passage_id!r} is invalid: {reason}")


def _encode(passage):

    return "\n".join(passage.lines)


def _to_passage(passage_id, text_lines):

    # Building the Passage re-applies its validation (uniform grid, Grade 1 characters).
    try:
        return Passage(text_lines.split("\n"))
    except ValueError as error:
        raise StoredPassageError(passage_id, str(error)) from error


def init_db(engine):
    """Create the passages table and make the `default` row match
    `build_default_passage`, so a changed default text reaches the database on
    the next run. Safe to run more than once, and from several processes at
    once."""

    params = {"id": DEFAULT_PASSAGE_ID, "text_lines": _encode(build_default_passage())}

    with engine.begin() as connection:

        connection.execute(text(CREATE_PASSAGES_TABLE))

        updated = connection.execute(
            text("UPDATE passages SET text_lines = :text_lines WHERE id = :id"), params
        ).rowcount

    if updated:
        return

    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO passages (id, text_lines) VALUES (:id, :text_lines)"), params)
    except IntegrityError:
        # Another process inserted the row between our UPDATE and INSERT; it
        # wrote the same text, so there is nothing left to do.
        pass


def get_passage(engine, passage_id):
    """The Passage stored under `passage_id`. Raises UnknownPassageError,
    which Session creation uses to reject an unknown id, and StoredPassageError
    if the row is not a valid Passage."""

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT text_lines FROM passages WHERE id = :id"), {"id": passage_id}
        ).first()

    if row is None:
        raise UnknownPassageError(passage_id)

    return _to_passage(passage_id, row.text_lines)


def list_passages(engine):
    """A summary of every valid stored Passage. An invalid row is logged and
    left out, so one bad row does not take the whole listing down."""

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT id, text_lines FROM passages ORDER BY id")).all()

    summaries = []

    for row in rows:
        try:
            summaries.append(passage_summary(row.id, _to_passage(row.id, row.text_lines)))
        except StoredPassageError as error:
            log_event(logger, "passage_skipped", level=logging.WARNING, passage_id=row.id, reason=error)

    return summaries


if __name__ == "__main__":

    database_url = load_settings().database_url

    if database_url is None:
        raise SystemExit("OCURATE_DATABASE_URL is not set")

    init_db(create_engine(database_url))
    print("passages table ready")
