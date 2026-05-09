import pytest
from fastapi.testclient import TestClient

from server.app import app, store


@pytest.fixture
def client():
    store._games.clear()
    return TestClient(app)


def _create(client) -> str:
    return client.post("/games").json()["code"]


def _add(client, code: str, name: str, preference: str = "BOTH", never_pitch: bool = False):
    return client.post(
        f"/games/{code}/players",
        json={"name": name, "preference": preference, "never_pitch": never_pitch},
    )


def _add_ten(client, code: str):
    """Add 10 BOTH-eligible players named P1..P10."""
    for i in range(1, 11):
        r = _add(client, code, f"P{i}", "BOTH")
        assert r.status_code == 201


def test_create_game_returns_code_and_setup_status(client):
    response = client.post("/games")
    assert response.status_code == 201
    body = response.json()
    assert len(body["code"]) == 4
    assert body["status"] == "setup"
    assert body["inning"] == 1
    assert body["players"] == []


def test_get_game_is_case_insensitive(client):
    code = _create(client)
    response = client.get(f"/games/{code.lower()}")
    assert response.status_code == 200
    assert response.json()["code"] == code


def test_get_game_missing_code_returns_404(client):
    assert client.get("/games/ZZZZ").status_code == 404


def test_add_player_appends_to_roster(client):
    code = _create(client)
    response = _add(client, code, "Jason", "IF", True)
    assert response.status_code == 201
    body = response.json()
    assert len(body["players"]) == 1
    assert body["players"][0]["name"] == "Jason"
    assert body["players"][0]["preference"] == "IF"
    assert body["players"][0]["never_pitch"] is True


def test_add_player_rejects_duplicate_name(client):
    code = _create(client)
    _add(client, code, "Jason", "IF")
    response = _add(client, code, "Jason", "OF")
    assert response.status_code == 409


def test_add_player_mid_game_seeds_to_team_average(client):
    code = _create(client)
    _add_ten(client, code)
    assert client.post(f"/games/{code}/start").status_code == 200
    assert client.post(f"/games/{code}/next-inning").status_code == 200

    response = _add(client, code, "Latecomer", "BOTH")
    assert response.status_code == 201

    new_player = next(p for p in response.json()["players"] if p["name"] == "Latecomer")
    assert new_player["innings_played"] >= 0
    assert new_player["innings_sat"] >= 0
    total = new_player["innings_played"] + new_player["innings_sat"]
    assert total > 0


def test_add_player_after_end_returns_409(client):
    code = _create(client)
    _add(client, code, "Jason", "IF")
    client.post(f"/games/{code}/start")
    client.post(f"/games/{code}/end")
    response = _add(client, code, "Latecomer", "BOTH")
    assert response.status_code == 409


def test_remove_player_drops_from_roster_and_locks(client):
    code = _create(client)
    _add(client, code, "Jason", "IF")
    _add(client, code, "Bob", "OF")
    client.put(
        f"/games/{code}/locks/SS",
        json={"player_name": "Jason"},
    )

    response = client.delete(f"/games/{code}/players/Jason")
    assert response.status_code == 200
    body = response.json()
    assert [p["name"] for p in body["players"]] == ["Bob"]
    assert body["locks"] == {}


def test_remove_player_not_in_roster_returns_404(client):
    code = _create(client)
    response = client.delete(f"/games/{code}/players/Ghost")
    assert response.status_code == 404


def test_edit_player_updates_preference_and_never_pitch(client):
    code = _create(client)
    _add(client, code, "Jason", "IF", False)

    response = client.patch(
        f"/games/{code}/players/Jason",
        json={"preference": "BOTH", "never_pitch": True},
    )
    assert response.status_code == 200
    player = response.json()["players"][0]
    assert player["preference"] == "BOTH"
    assert player["never_pitch"] is True


def test_lock_position_assigns_player(client):
    code = _create(client)
    _add(client, code, "Jason", "IF")

    response = client.put(
        f"/games/{code}/locks/P",
        json={"player_name": "Jason"},
    )
    assert response.status_code == 200
    assert response.json()["locks"] == {"P": "Jason"}


def test_lock_position_moves_player_from_previous_lock(client):
    code = _create(client)
    _add(client, code, "Jason", "BOTH")
    client.put(f"/games/{code}/locks/P", json={"player_name": "Jason"})

    response = client.put(f"/games/{code}/locks/SS", json={"player_name": "Jason"})
    assert response.status_code == 200
    assert response.json()["locks"] == {"SS": "Jason"}


def test_lock_position_unknown_player_returns_404(client):
    code = _create(client)
    response = client.put(f"/games/{code}/locks/P", json={"player_name": "Ghost"})
    assert response.status_code == 404


def test_unlock_position_resets_sit_count_and_clears_lock(client):
    code = _create(client)
    _add_ten(client, code)
    client.put(f"/games/{code}/locks/P", json={"player_name": "P1"})
    client.post(f"/games/{code}/start")
    client.post(f"/games/{code}/next-inning")
    client.post(f"/games/{code}/next-inning")

    response = client.delete(f"/games/{code}/locks/P")
    assert response.status_code == 200
    body = response.json()
    assert "P" not in body["locks"]


def test_unlock_position_not_locked_returns_404(client):
    code = _create(client)
    response = client.delete(f"/games/{code}/locks/P")
    assert response.status_code == 404


def test_start_with_empty_roster_succeeds(client):
    code = _create(client)
    response = client.post(f"/games/{code}/start")
    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"


def test_start_transitions_to_in_progress_with_first_assignment(client):
    code = _create(client)
    _add_ten(client, code)
    response = client.post(f"/games/{code}/start")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "in_progress"
    assert body["last_assignment"] is not None
    assert body["last_assignment"]["inning"] == 1


def test_start_twice_returns_409(client):
    code = _create(client)
    _add_ten(client, code)
    client.post(f"/games/{code}/start")
    response = client.post(f"/games/{code}/start")
    assert response.status_code == 409


def test_next_inning_advances_inning_counter(client):
    code = _create(client)
    _add_ten(client, code)
    client.post(f"/games/{code}/start")
    response = client.post(f"/games/{code}/next-inning")
    assert response.status_code == 200
    body = response.json()
    assert body["inning"] == 2
    assert body["last_assignment"]["inning"] == 2


def test_next_inning_before_start_returns_409(client):
    code = _create(client)
    _add_ten(client, code)
    response = client.post(f"/games/{code}/next-inning")
    assert response.status_code == 409


def test_end_game_transitions_status(client):
    code = _create(client)
    _add(client, code, "Jason", "IF")
    client.post(f"/games/{code}/start")
    response = client.post(f"/games/{code}/end")
    assert response.status_code == 200
    assert response.json()["status"] == "ended"


def test_swap_with_bench_player(client):
    code = _create(client)
    for i in range(1, 12):
        _add(client, code, f"P{i}", "BOTH")
    client.post(f"/games/{code}/start")

    body = client.get(f"/games/{code}").json()
    bench = body["last_assignment"]["bench"]
    assert len(bench) == 1
    benched = bench[0]
    target_pos = next(
        pos for pos, name in body["last_assignment"]["positions"].items()
        if name is not None and name != benched
    )
    displaced = body["last_assignment"]["positions"][target_pos]

    response = client.post(
        f"/games/{code}/swap",
        json={"position": target_pos, "player_name": benched},
    )
    assert response.status_code == 200
    new_assignment = response.json()["last_assignment"]
    assert new_assignment["positions"][target_pos] == benched
    assert displaced in new_assignment["bench"]
    assert benched not in new_assignment["bench"]


def test_swap_between_two_field_players_swaps_positions(client):
    code = _create(client)
    _add_ten(client, code)
    client.post(f"/games/{code}/start")

    body = client.get(f"/games/{code}").json()
    positions = body["last_assignment"]["positions"]
    filled = [(pos, name) for pos, name in positions.items() if name is not None]
    pos_a, name_a = filled[0]
    pos_b, name_b = filled[1]

    response = client.post(
        f"/games/{code}/swap",
        json={"position": pos_a, "player_name": name_b},
    )
    assert response.status_code == 200
    new_positions = response.json()["last_assignment"]["positions"]
    assert new_positions[pos_a] == name_b
    assert new_positions[pos_b] == name_a


def test_swap_into_locked_position_returns_409(client):
    code = _create(client)
    _add_ten(client, code)
    client.put(f"/games/{code}/locks/P", json={"player_name": "P1"})
    client.post(f"/games/{code}/start")

    response = client.post(
        f"/games/{code}/swap",
        json={"position": "P", "player_name": "P2"},
    )
    assert response.status_code == 409


def test_swap_with_locked_player_returns_409(client):
    code = _create(client)
    _add_ten(client, code)
    client.put(f"/games/{code}/locks/P", json={"player_name": "P1"})
    client.post(f"/games/{code}/start")

    response = client.post(
        f"/games/{code}/swap",
        json={"position": "SS", "player_name": "P1"},
    )
    assert response.status_code == 409


def test_swap_before_start_returns_409(client):
    code = _create(client)
    _add_ten(client, code)
    response = client.post(
        f"/games/{code}/swap",
        json={"position": "SS", "player_name": "P1"},
    )
    assert response.status_code == 409
