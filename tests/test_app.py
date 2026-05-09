from fastapi.testclient import TestClient

from server.app import app, store


def test_create_game_returns_code_and_setup_status():
    store._games.clear()
    client = TestClient(app)

    response = client.post("/games")

    assert response.status_code == 201
    body = response.json()
    assert "code" in body
    assert len(body["code"]) == 4
    assert body["status"] == "setup"
    assert body["inning"] == 1
    assert body["players"] == []


def test_get_game_returns_state_for_existing_code():
    store._games.clear()
    client = TestClient(app)

    code = client.post("/games").json()["code"]
    response = client.get(f"/games/{code}")

    assert response.status_code == 200
    assert response.json()["code"] == code


def test_get_game_is_case_insensitive():
    store._games.clear()
    client = TestClient(app)

    code = client.post("/games").json()["code"]
    response = client.get(f"/games/{code.lower()}")

    assert response.status_code == 200
    assert response.json()["code"] == code


def test_get_game_missing_code_returns_404():
    store._games.clear()
    client = TestClient(app)

    response = client.get("/games/ZZZZ")
    assert response.status_code == 404
