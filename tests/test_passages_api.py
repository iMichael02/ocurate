import pytest
from fastapi.testclient import TestClient

from app import create_app
from config import Settings
from passage import PASSAGES, UnknownPassageError, get_passage
from reading_session import ReadingSession


@pytest.fixture
def client():
    return TestClient(create_app(Settings()))


def test_listing_serves_every_registered_passage(client):

    response = client.get("/passages")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == list(PASSAGES)


@pytest.mark.parametrize("passage_id", list(PASSAGES))
def test_single_passage_matches_the_passage_logic(client, passage_id):

    passage = PASSAGES[passage_id]

    response = client.get(f"/passages/{passage_id}")

    assert response.status_code == 200
    assert response.json() == {
        "id": passage_id,
        "lines": passage.lines,
        "braille_lines": passage.braille_lines,
        "rows": passage.num_rows,
        "columns": passage.num_columns,
        "char_count": passage.char_count,
        "word_count": passage.word_count,
        "first_cell": {"row": passage.first_cell[0], "col": passage.first_cell[1]},
        "last_cell": {"row": passage.last_cell[0], "col": passage.last_cell[1]},
    }


def test_listing_and_single_endpoint_agree(client):

    for item in client.get("/passages").json():
        assert client.get(f"/passages/{item['id']}").json() == item


def test_unknown_passage_is_not_found(client):

    response = client.get("/passages/no-such-passage")

    assert response.status_code == 404
    assert response.json() == {"detail": "unknown passage id"}


def test_get_passage_rejects_an_unknown_id():

    with pytest.raises(UnknownPassageError):
        get_passage("no-such-passage")


@pytest.mark.parametrize("passage_id", list(PASSAGES))
def test_served_counts_are_what_reading_speed_uses(client, passage_id):

    served = client.get(f"/passages/{passage_id}").json()

    session = ReadingSession(get_passage(passage_id))
    session.register_fixation(served["first_cell"]["row"], served["first_cell"]["col"], timestamp=0.0)
    session.register_fixation(served["last_cell"]["row"], served["last_cell"]["col"], timestamp=60.0)

    # Over exactly one minute, CPM and WPM equal the counts they divide.
    result = session.result()
    assert result["cpm"] == pytest.approx(served["char_count"])
    assert result["wpm"] == pytest.approx(served["word_count"])
