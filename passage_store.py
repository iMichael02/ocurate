from sqlalchemy import create_engine, text

from config import load_settings
from passage import Passage, UnknownPassageError, build_default_passage, passage_summary

# One row per Passage. `text_lines` holds the plain-text rows joined with "\n";
# Passage lines are lowercase letters and spaces only, so the newline is
# unambiguous. (`lines` itself is a reserved word in MySQL.)
CREATE_PASSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS passages (
    id VARCHAR(64) PRIMARY KEY,
    text_lines TEXT NOT NULL
)
"""


def init_db(engine):
    """Create the passages table and insert the default Passage if it is
    missing. Safe to run more than once."""

    with engine.begin() as connection:

        connection.execute(text(CREATE_PASSAGES_TABLE))

        exists = connection.execute(text("SELECT 1 FROM passages WHERE id = :id"), {"id": "default"}).first()

        if exists is None:
            connection.execute(
                text("INSERT INTO passages (id, text_lines) VALUES (:id, :text_lines)"),
                {"id": "default", "text_lines": "\n".join(build_default_passage().lines)},
            )


def _to_passage(text_lines):

    # Building the Passage re-applies its validation (uniform grid, Grade 1 characters).
    return Passage(text_lines.split("\n"))


def get_passage(engine, passage_id):
    """The Passage stored under `passage_id`. Raises UnknownPassageError,
    which Session creation uses to reject an unknown id."""

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT text_lines FROM passages WHERE id = :id"), {"id": passage_id}
        ).first()

    if row is None:
        raise UnknownPassageError(passage_id)

    return _to_passage(row.text_lines)


def list_passages(engine):

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT id, text_lines FROM passages ORDER BY id")).all()

    return [passage_summary(row.id, _to_passage(row.text_lines)) for row in rows]


if __name__ == "__main__":

    database_url = load_settings().database_url

    if database_url is None:
        raise SystemExit("OCURATE_DATABASE_URL is not set")

    init_db(create_engine(database_url))
    print("passages table ready")
