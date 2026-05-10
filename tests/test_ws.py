import pytest
from fastapi.testclient import TestClient

from server.app import app, store, ws_manager


@pytest.fixture
def client():
    store._games.clear()
    return TestClient(app)


def _create(client) -> str:
    return client.post("/games").json()["code"]


def _add(client, code, name, preference="BOTH"):
    return client.post(
        f"/games/{code}/players",
        json={"name": name, "preference": preference},
    )


def test_ws_sends_initial_state_on_connect(client):
    code = _create(client)
    _add(client, code, "Jason", "IF")

    with client.websocket_connect(f"/ws/{code}") as ws:
        html = ws.receive_text()

    assert code in html
    assert "Jason" in html
    assert 'id="scoreboard"' in html


def test_ws_unknown_code_closes_connection(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/ZZZZ") as ws:
            ws.receive_text()


def test_ws_broadcasts_state_change(client):
    code = _create(client)

    with client.websocket_connect(f"/ws/{code}") as ws:
        ws.receive_text()
        _add(client, code, "Jason", "IF")
        html = ws.receive_text()

    assert "Jason" in html


def test_ws_broadcasts_to_multiple_clients(client):
    code = _create(client)

    with client.websocket_connect(f"/ws/{code}") as a, client.websocket_connect(
        f"/ws/{code}"
    ) as b:
        a.receive_text()
        b.receive_text()

        _add(client, code, "Jason", "IF")

        html_a = a.receive_text()
        html_b = b.receive_text()

    assert "Jason" in html_a
    assert "Jason" in html_b


def test_ws_disconnect_cleans_up_connection(client):
    code = _create(client)

    with client.websocket_connect(f"/ws/{code}") as ws:
        ws.receive_text()
        assert ws_manager.connection_count(code) == 1

    assert ws_manager.connection_count(code) == 0


def test_ws_broadcasts_inning_advance(client):
    code = _create(client)
    for i in range(1, 11):
        _add(client, code, f"P{i}")
    client.post(f"/games/{code}/start")

    with client.websocket_connect(f"/ws/{code}") as ws:
        ws.receive_text()
        client.post(f"/games/{code}/next-inning")
        html = ws.receive_text()

    assert "2nd Inning" in html
