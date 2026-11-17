import json

import pytest
from fastapi.testclient import TestClient

from benchmark import browser_timing


def _summary():

    group = {"n": 200, "median_ms": 12.5, "p95_ms": 20.0, "mean_ms": 13.1}

    return {"without_centres": group, "with_centres": {**group, "median_ms": 14.0}, "no_face": 3, "frames": 410,
            "achieved_fps": 28.4, "user_agent": "Chrome", "cores": 8}


@pytest.fixture
def served(tmp_path):

    (tmp_path / "js").mkdir()
    (tmp_path / "js" / "a.js").write_text("export {}")
    (tmp_path / ".env").write_text("secret")
    reports = []

    return TestClient(browser_timing.create_app(tmp_path, report=reports.append)), reports


def test_a_valid_summary_is_reported_as_one_json_line(served):

    client, reports = served

    assert client.post("/result", json=_summary()).status_code == 200
    assert json.loads(reports[0])["timing"]["with_centres"]["median_ms"] == 14.0


@pytest.mark.parametrize("change", [
    lambda s: s["with_centres"].update(extra=1),                  # only the agreed fields
    lambda s: s["without_centres"].update(median_ms="fast"),
    lambda s: s["without_centres"].update(median_ms=float("nan")),
    lambda s: s.pop("with_centres"),
    lambda s: s.update(frames=True),
])
def test_anything_that_is_not_plain_timing_numbers_is_refused(served, change):

    client, reports = served
    summary = _summary()
    change(summary)

    assert client.post("/result", content=json.dumps(summary).replace("NaN", "null"),
                       headers={"content-type": "application/json"}).status_code == 422
    assert reports == []


def test_extra_top_level_fields_are_dropped_not_reported(served):

    client, reports = served
    client.post("/result", json={**_summary(), "landmarks": [[0.1, 0.2]]})

    assert "landmarks" not in reports[0]


def test_pages_and_only_the_frontends_js_and_css_are_served(served):

    client, _ = served

    assert "Browser timing" in client.get("/").text
    assert client.get("/timing.js").status_code == 200
    assert client.get("/fe/js/a.js").status_code == 200
    assert client.get("/fe/.env").status_code == 404
