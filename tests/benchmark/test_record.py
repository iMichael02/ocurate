import stat

import pytest
from fastapi.testclient import TestClient

from app.analysis.calibration import CALIBRATION_POINTS
from benchmark import record
from benchmark.metrics import Geometry
from benchmark.pipeline import replay
from benchmark.recording import load
from benchmark.synthetic import generate_learner, passage_cells

GEOMETRY = Geometry(34.4, 19.4, 60.0)


def _frame(frame):

    return None if frame is None else frame.model_dump(exclude_none=True, exclude={"type", "target"})


def _payload():
    """What the recorder page posts, built from a simulated Learner."""

    source = generate_learner("src", seed=1)
    cells = passage_cells()
    cell_of = {(c.x + c.w / 2, c.y + c.h / 2): (c.row, c.col) for c in cells}

    return {
        "cells": [c.model_dump() for c in cells],
        "calibration": [{"target": CALIBRATION_POINTS.index(t), "frame": _frame(f)} for t, f in source.calibration],
        "reading": [{"row": cell_of[t][0], "col": cell_of[t][1], "frame": _frame(f)} for t, f in source.reading],
    }


@pytest.fixture
def served(tmp_path):

    output = tmp_path / "data" / "p01.json"
    frontend = tmp_path / "fe"
    (frontend / "js").mkdir(parents=True)
    (frontend / "js" / "a.js").write_text("export {}")
    (frontend / ".env").write_text("secret")
    (frontend / "package.json").write_text("{}")
    app = record.create_app("p01", GEOMETRY, {"lighting": "dim"}, frontend, output)

    return TestClient(app), output


def test_a_posted_recording_is_saved_and_can_be_replayed(served):

    client, output = served

    response = client.post("/recording", json=_payload())

    assert response.status_code == 200 and response.json()["saved"]
    recording = load(output)
    assert recording.learner == "p01"
    assert recording.conditions == {"lighting": "dim"}
    assert recording.geometry == GEOMETRY
    assert replay(recording).calibrated


def test_targets_and_truth_come_from_the_grid_and_layout_not_from_the_page(served):

    client, output = served
    payload = _payload()
    payload["calibration"][0]["target"] = 15
    payload["reading"][0].update(row=2, col=13)

    client.post("/recording", json=payload)

    recording = load(output)
    assert recording.calibration[0][0] == pytest.approx(CALIBRATION_POINTS[15])
    cell = next(c for c in recording.cells if (c.row, c.col) == (2, 13))
    assert recording.reading[0][0] == pytest.approx((cell.x + cell.w / 2, cell.y + cell.h / 2))


def test_the_recording_file_is_private_and_never_overwritten(served):

    client, output = served
    client.post("/recording", json=_payload())

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert client.post("/recording", json=_payload()).status_code == 409   # one Learner per recorder run


def test_an_existing_file_is_not_replaced_without_overwrite(tmp_path):

    output = tmp_path / "p01.json"
    output.write_text("keep me")
    client = TestClient(record.create_app("p01", GEOMETRY, {}, tmp_path, output))

    response = client.post("/recording", json=_payload())

    assert response.status_code == 409
    assert output.read_text() == "keep me"


@pytest.mark.parametrize("change", [
    lambda p: p["calibration"][5].update(target=16),
    lambda p: p["calibration"][5].update(target=True),
    lambda p: p["reading"][3].update(row=9),
    lambda p: p["cells"].pop(),
    lambda p: p["calibration"][5].update(frame={"t": 1}),
    lambda p: p["calibration"][5]["frame"].update(target={"x": 0.1, "y": 0.1}),
    lambda p: p["calibration"][10]["frame"].update(t=0.0),     # time goes backwards
    lambda p: p.update(reading=[]),
    lambda p: p.pop("cells"),
])
def test_invalid_payloads_are_rejected_and_nothing_is_written(served, change):

    client, output = served
    payload = _payload()
    change(payload)

    response = client.post("/recording", json=payload)

    assert response.status_code == 422
    assert not output.exists()


def test_a_rejection_message_does_not_echo_landmark_values(served):

    client, _ = served
    payload = _payload()
    payload["calibration"][5]["frame"]["iris"][0]["x"] = 99.123456

    reason = client.post("/recording", json=payload).json()["reason"]

    assert "99.123456" not in reason


def test_only_json_is_accepted(served):

    client, _ = served

    assert client.post("/recording", content="{}", headers={"content-type": "text/plain"}).status_code == 415


def test_only_the_frontends_js_and_css_are_served(served):

    client, _ = served

    assert client.get("/fe/js/a.js").status_code == 200
    assert client.get("/fe/.env").status_code == 404
    assert client.get("/fe/package.json").status_code == 404
    assert client.get("/fe/js/../.env").status_code == 404
    assert client.get("/fe/js/%2e%2e/.env").status_code == 404


def test_the_page_and_config_are_served(served):

    client, _ = served

    assert "Gaze recorder" in client.get("/").text
    assert client.get("/recorder.js").status_code == 200
    assert client.get("/config").json()["lines"] == ["read the texts", "with your eyes", "and count them"]


def test_quality_warnings_flag_a_missing_face_and_thin_targets():

    recording = record.build_recording(_payload(), "p01", GEOMETRY, {})
    assert record.quality_warnings(recording) == []

    recording.calibration = [(t, None) for t, _ in recording.calibration]
    warnings = record.quality_warnings(recording)

    assert any("calibration targets have fewer" in w for w in warnings)
    assert any("a face was found in only 0% of the calibration" in w for w in warnings)


def test_conditions_and_screen_are_parsed_strictly():

    assert record.parse_conditions(["lighting=dim", "head=still"]) == {"lighting": "dim", "head": "still"}
    assert record.parse_screen("34.4x19.4") == (34.4, 19.4)
    for bad in ["lighting", "Lighting=dim", "x="]:
        with pytest.raises(ValueError):
            record.parse_conditions([bad])
    for bad in ["34", "0x10", "axb"]:
        with pytest.raises(ValueError):
            record.parse_screen(bad)


def test_the_cli_refuses_without_consent_or_with_a_name_like_id(tmp_path):

    base = ["--learner", "p01", "--screen-cm", "34x19", "--distance-cm", "60", "--data", str(tmp_path)]

    with pytest.raises(SystemExit, match="consent"):
        record.main(base)
    with pytest.raises(SystemExit, match="pseudonym"):
        record.main(["--learner", "Jane Doe", *base[2:], "--consent"])
