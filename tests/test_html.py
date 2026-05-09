import pytest
from fastapi.testclient import TestClient

from server.app import app, store


@pytest.fixture
def client():
    store._games.clear()
    return TestClient(app)


def _create(client) -> str:
    return client.post("/games").json()["code"]


def test_index_renders_landing_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Create new game" in response.text
    assert "Join" in response.text


def test_create_game_form_redirects_to_game_page(client):
    response = client.post("/games/new", follow_redirects=False)
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/games/")
    code = location.removeprefix("/games/")
    assert len(code) == 4
    assert store.get(code) is not None


def test_join_with_valid_code_redirects(client):
    code = _create(client)
    response = client.get(f"/join?code={code}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/games/{code}"


def test_join_lowercase_redirects_to_uppercase(client):
    code = _create(client)
    response = client.get(f"/join?code={code.lower()}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/games/{code}"


def test_join_unknown_code_redirects_to_index(client):
    response = client.get("/join?code=ZZZZ", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/?error=notfound"


def test_game_page_renders_html_when_accept_html(client):
    code = _create(client)
    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert code in response.text
    assert 'ws-connect="/ws/' in response.text
    assert 'id="scoreboard"' in response.text


def test_game_page_returns_json_without_html_accept(client):
    code = _create(client)
    response = client.get(f"/games/{code}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["code"] == code


def test_add_player_form_creates_player_and_returns_204(client):
    code = _create(client)
    response = client.post(
        f"/games/{code}/players-form",
        data={"name": "Jason", "preference": "IF", "never_pitch": "on"},
    )
    assert response.status_code == 204

    body = client.get(f"/games/{code}").json()
    assert body["players"][0]["name"] == "Jason"
    assert body["players"][0]["preference"] == "IF"
    assert body["players"][0]["never_pitch"] is True


def test_add_player_form_without_never_pitch_defaults_false(client):
    code = _create(client)
    response = client.post(
        f"/games/{code}/players-form",
        data={"name": "Bob", "preference": "OF"},
    )
    assert response.status_code == 204
    body = client.get(f"/games/{code}").json()
    assert body["players"][0]["never_pitch"] is False


def test_setup_scoreboard_shows_roster_and_start_button(client):
    code = _create(client)
    client.post(f"/games/{code}/players-form", data={"name": "Jason", "preference": "IF"})
    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    assert "Jason" in response.text
    assert "Start game" in response.text


def test_in_progress_scoreboard_shows_inning_and_lineup(client):
    code = _create(client)
    for i in range(1, 11):
        client.post(
            f"/games/{code}/players-form",
            data={"name": f"P{i}", "preference": "BOTH"},
        )
    client.post(f"/games/{code}/start")

    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    assert "Inning 1" in response.text
    assert "Next inning" in response.text
    assert ">P<" in response.text


def test_ended_scoreboard_shows_end_message(client):
    code = _create(client)
    client.post(f"/games/{code}/players-form", data={"name": "Jason", "preference": "IF"})
    client.post(f"/games/{code}/start")
    client.post(f"/games/{code}/end")

    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    assert "Game ended" in response.text
    assert "New game" in response.text
