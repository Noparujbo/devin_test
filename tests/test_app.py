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


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    import app.db
    importlib.reload(app.db)
    app.db.init_db()
    yield app.db


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


def test_delete_link_cascades_to_clicks(db):
    # Test database-level ON DELETE CASCADE by directly manipulating the database
    # to bypass the manual cascade-delete logic in the API endpoint
    with db.get_conn() as conn:
        # Insert a link directly
        code = "testcode123"
        conn.execute(
            "INSERT INTO links (code, long_url, created_at, click_count) VALUES (?, ?, ?, 0)",
            (code, "https://example.com", "2024-01-01T00:00:00Z"),
        )
        
        # Insert clicks directly
        conn.execute(
            "INSERT INTO clicks (code, clicked_at, referer, user_agent) VALUES (?, ?, ?, ?)",
            (code, "2024-01-01T00:00:00Z", "https://google.com", "Mozilla/5.0"),
        )
        conn.execute(
            "INSERT INTO clicks (code, clicked_at, referer, user_agent) VALUES (?, ?, ?, ?)",
            (code, "2024-01-01T00:01:00Z", "https://twitter.com", "Mozilla/5.0"),
        )
        conn.execute(
            "INSERT INTO clicks (code, clicked_at, referer, user_agent) VALUES (?, ?, ?, ?)",
            (code, "2024-01-01T00:02:00Z", None, "Mozilla/5.0"),
        )
        
        # Verify clicks exist
        clicks_count = conn.execute("SELECT COUNT(*) FROM clicks WHERE code = ?", (code,)).fetchone()[0]
        assert clicks_count == 3
        
        # Delete the link directly (bypassing API endpoint that has manual cascade)
        conn.execute("DELETE FROM links WHERE code = ?", (code,))
        
        # Verify clicks are also deleted due to ON DELETE CASCADE
        clicks_count_after = conn.execute("SELECT COUNT(*) FROM clicks WHERE code = ?", (code,)).fetchone()[0]
        assert clicks_count_after == 0
