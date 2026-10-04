from fastapi.testclient import TestClient

from app import create_app
from config import Settings


def test_health_endpoint_answers_ok():

    client = TestClient(create_app(Settings()))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_app_carries_the_settings_it_was_given():

    settings = Settings(max_concurrent_sessions=3)

    assert create_app(settings).state.settings.max_concurrent_sessions == 3
