import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    import app.db
    import app.main

    importlib.reload(app.db)
    importlib.reload(app.main)
    with TestClient(app.main.app) as test_client:
        yield test_client


def test_shorten_and_redirect_tracks_clicks(client):
    created = client.post("/api/shorten", json={"url": "example.com/docs"}).json()
    assert created["long_url"] == "https://example.com/docs"
    code = created["code"]

    redirect = client.get(f"/{code}", follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers["location"] == "https://example.com/docs"

    link = client.get("/api/links").json()["links"][0]
    assert link["click_count"] == 1
    assert link["last_clicked_at"] is not None

    clicks = client.get(f"/api/links/{code}/clicks").json()["clicks"]
    assert len(clicks) == 1


def test_custom_code_and_conflict(client):
    assert client.post("/api/shorten", json={"url": "https://a.dev", "custom_code": "mine"}).json()["code"] == "mine"
    assert client.post("/api/shorten", json={"url": "https://b.dev", "custom_code": "mine"}).status_code == 409


def test_invalid_url_rejected(client):
    assert client.post("/api/shorten", json={"url": "ftp://nope"}).status_code == 422


def test_unknown_code_404(client):
    assert client.get("/nothere", follow_redirects=False).status_code == 404


def test_delete_link(client):
    code = client.post("/api/shorten", json={"url": "https://a.dev"}).json()["code"]
    assert client.delete(f"/api/links/{code}").status_code == 200
    assert client.get("/api/links").json()["links"] == []
