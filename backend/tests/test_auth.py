"""Optionaler Zugangsschutz: API-Schlüssel, Dashboard-Anmeldung, offener Standard."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_without_key_everything_is_open(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/jobs").status_code == 200
        assert client.get("/api/auth/status").json() == {"required": False, "authenticated": True}


def test_api_key_protects_api_and_v1(settings):
    settings.api_key = "geheim-123"
    with TestClient(create_app(settings)) as client:
        health = client.get("/health").json()  # bleibt offen, verrät aber nichts
        assert health == {"wrapper": "online", "language": "de", "auth_required": True}
        assert client.get("/api/jobs").status_code == 401
        assert client.post("/v1/audio/transcriptions").status_code == 401
        assert client.get("/api/jobs", headers={"Authorization": "Bearer falsch"}).status_code == 401
        assert client.get("/api/jobs", headers={"Authorization": "Bearer geheim-123"}).status_code == 200
        # Link im Browser → Anmeldung, danach zurück
        r = client.get("/api/jobs/abc/summary?x=1", headers={"Accept": "text/html"}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/dashboard/?next=%2Fapi%2Fjobs%2Fabc%2Fsummary%3Fx%3D1"

        # Dashboard: ohne eigenes Passwort mit dem API-Schlüssel anmelden
        assert client.post("/api/auth/login", json={"password": "falsch"}).status_code == 401
        assert client.post("/api/auth/login", json={"password": "geheim-123"}).status_code == 204
        assert client.get("/api/jobs").status_code == 200
        assert client.get("/api/auth/status").json() == {"required": True, "authenticated": True}
        client.post("/api/auth/logout")
        assert client.get("/api/jobs").status_code == 401


def test_dashboard_password_and_change_invalidates_sessions(settings):
    settings.dashboard_password = "pw"
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/jobs").status_code == 401
        assert client.post("/api/auth/login", json={"password": "pw"}).status_code == 204
        assert client.get("/api/jobs").status_code == 200

        # Passwort im Dashboard ändern: die eigene Sitzung bleibt, alte Cookies werden ungültig
        old_cookie = client.cookies.get("wn_session")
        r = client.put("/api/settings", json={"values": {"dashboard_password": "neu"}})
        assert r.status_code == 200 and "dashboard_password" in r.json()["changed"]
        assert all(f["value"] is None for g in r.json()["groups"] for f in g["fields"] if f["kind"] == "secret")
        assert client.get("/api/jobs").status_code == 200
        client.cookies.clear()
        client.cookies.set("wn_session", old_cookie)
        assert client.get("/api/jobs").status_code == 401
