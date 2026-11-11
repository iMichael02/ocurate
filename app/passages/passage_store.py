import logging
import time

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.config import load_settings
from app.log_setup import log_event
from app.passages.passage import Passage, UnknownPassageError, build_default_passage, build_short_passage
from app.schemas.passage import passage_summary

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
SHORT_PASSAGE_ID = "short"

# The Passages every database starts with. `init_db` keeps each row equal to the text in code.
SEED_PASSAGES = {
    DEFAULT_PASSAGE_ID: build_default_passage,
    SHORT_PASSAGE_ID: build_short_passage,
}


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
    """Migrate and seed: create the passages table, then make every row in
    `SEED_PASSAGES` match the text in code, so a changed seed text reaches the
    database on the next run. Passages added some other way are left alone.
    Safe to run more than once, and from several processes at once."""

    with engine.begin() as connection:
        connection.execute(text(CREATE_PASSAGES_TABLE))

    for passage_id, build in SEED_PASSAGES.items():
        _upsert_passage(engine, passage_id, build())


def _upsert_passage(engine, passage_id, passage):

    params = {"id": passage_id, "text_lines": _encode(passage)}

    with engine.begin() as connection:
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


def wait_and_init_db(engine, attempts=30, delay_seconds=2, sleep=time.sleep):
    """`init_db`, retried while the database is still starting. Raises the last
    error if it never becomes reachable."""

    for attempt in range(1, attempts + 1):
        try:
            init_db(engine)
            return
        except OperationalError as error:
            if attempt == attempts:
                raise

            print(f"database not ready (attempt {attempt}/{attempts}): {error.orig}")
            sleep(delay_seconds)


if __name__ == "__main__":

    database_url = load_settings().database_url

    if database_url is None:
        raise SystemExit("OCURATE_DATABASE_URL is not set")

    wait_and_init_db(create_engine(database_url))
    print(f"passages table ready, seeded: {', '.join(SEED_PASSAGES)}")
