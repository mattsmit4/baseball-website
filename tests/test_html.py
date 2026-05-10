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
    assert "Fair defensive rotation" in response.text


def test_index_shows_notfound_error_banner(client):
    response = client.get("/?error=notfound")
    assert response.status_code == 200
    assert "No game found with that code" in response.text


def test_index_no_error_banner_without_error_param(client):
    response = client.get("/")
    assert "No game found with that code" not in response.text


def test_create_game_form_redirects_to_game_page(client):
    response = client.post(
        "/games/new",
        data={"team_name": "Bombers"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/games/")
    code = location.removeprefix("/games/")
    assert len(code) == 4
    game = store.get(code)
    assert game is not None
    assert game.state.team_name == "Bombers"


def test_create_game_form_requires_team_name(client):
    response = client.post("/games/new", data={"team_name": "   "}, follow_redirects=False)
    assert response.status_code == 400


def test_create_game_form_caps_team_name_at_16_chars(client):
    response = client.post(
        "/games/new",
        data={"team_name": "x" * 17},
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_index_team_name_input_has_maxlength_16(client):
    response = client.get("/")
    assert 'name="team_name"' in response.text
    assert 'maxlength="16"' in response.text


def test_in_progress_scoreboard_uses_team_name_and_opponents_label(client):
    response = client.post(
        "/games/new",
        data={"team_name": "Bombers"},
        follow_redirects=False,
    )
    code = response.headers["location"].removeprefix("/games/")
    client.post(f"/games/{code}/players-form", data={"name": "P1", "preference": "BOTH"})
    client.post(f"/games/{code}/start")

    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    text = response.text
    assert ">Bombers<" in text
    assert ">Opponents<" in text
    assert ">Us<" not in text
    assert ">Them<" not in text


def test_remove_player_clears_them_from_last_assignment_immediately(client):
    code = _create(client)
    for i in range(1, 11):
        client.post(
            f"/games/{code}/players-form",
            data={"name": f"P{i}", "preference": "BOTH"},
        )
    client.post(f"/games/{code}/start")

    body_before = client.get(f"/games/{code}").json()
    on_field_player = next(
        name for name in body_before["last_assignment"]["positions"].values() if name
    )

    client.delete(f"/games/{code}/players/{on_field_player}")

    body_after = client.get(f"/games/{code}").json()
    assert on_field_player not in body_after["last_assignment"]["positions"].values()
    assert on_field_player not in body_after["last_assignment"]["bench"]


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
        data={"name": "Jason", "preference": "IF"},
    )
    assert response.status_code == 204

    body = client.get(f"/games/{code}").json()
    assert body["players"][0]["name"] == "Jason"
    assert body["players"][0]["preference"] == "IF"


def test_setup_scoreboard_shows_roster_and_start_button(client):
    code = _create(client)
    client.post(f"/games/{code}/players-form", data={"name": "Jason", "preference": "IF"})
    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    assert "Jason" in response.text
    assert "Start game" in response.text


def test_setup_scoreboard_renders_friendly_preference_label(client):
    code = _create(client)
    client.post(f"/games/{code}/players-form", data={"name": "Jason", "preference": "OF"})
    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    assert "Outfield" in response.text
    assert "Preference.OUTFIELD" not in response.text


def test_setup_page_includes_tap_to_copy_code_button(client):
    code = _create(client)
    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    assert "navigator.clipboard.writeText" in response.text
    assert "tap code to copy" in response.text


def test_in_progress_page_hides_code_header(client):
    code = _create(client)
    client.post(f"/games/{code}/players-form", data={"name": "P1", "preference": "BOTH"})
    client.post(f"/games/{code}/start")

    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    assert "tap code to copy" not in response.text
    assert "navigator.clipboard.writeText" not in response.text


def test_in_progress_page_includes_add_player_form(client):
    code = _create(client)
    for i in range(1, 11):
        client.post(
            f"/games/{code}/players-form",
            data={"name": f"P{i}", "preference": "BOTH"},
        )
    client.post(f"/games/{code}/start")

    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    assert ">Add a player<" in response.text
    assert f"hx-post=\"/games/{code}/players-form\"" in response.text


def test_in_progress_add_player_seeds_to_team_average(client):
    code = _create(client)
    for i in range(1, 11):
        client.post(
            f"/games/{code}/players-form",
            data={"name": f"P{i}", "preference": "BOTH"},
        )
    client.post(f"/games/{code}/start")
    client.post(f"/games/{code}/next-inning")

    response = client.post(
        f"/games/{code}/players-form",
        data={"name": "Latecomer", "preference": "BOTH"},
    )
    assert response.status_code == 204

    body = client.get(f"/games/{code}").json()
    latecomer = next(p for p in body["players"] if p["name"] == "Latecomer")
    assert latecomer["innings_played"] + latecomer["innings_sat"] > 0


def test_in_progress_add_player_appears_on_bench_immediately(client):
    code = _create(client)
    for i in range(1, 11):
        client.post(
            f"/games/{code}/players-form",
            data={"name": f"P{i}", "preference": "BOTH"},
        )
    client.post(f"/games/{code}/start")

    body_before = client.get(f"/games/{code}").json()
    assert "Latecomer" not in body_before["last_assignment"]["bench"]

    client.post(
        f"/games/{code}/players-form",
        data={"name": "Latecomer", "preference": "BOTH"},
    )

    body_after = client.get(f"/games/{code}").json()
    assert "Latecomer" in body_after["last_assignment"]["bench"]


def test_add_player_form_returns_409_on_duplicate_name(client):
    code = _create(client)
    client.post(f"/games/{code}/players-form", data={"name": "Jason", "preference": "IF"})

    response = client.post(
        f"/games/{code}/players-form",
        data={"name": "Jason", "preference": "OF"},
    )
    assert response.status_code == 409


def test_add_player_form_caps_name_at_16_chars(client):
    code = _create(client)
    response = client.post(
        f"/games/{code}/players-form",
        data={"name": "x" * 17, "preference": "BOTH"},
    )
    assert response.status_code == 400


def test_add_player_form_strips_whitespace(client):
    code = _create(client)
    response = client.post(
        f"/games/{code}/players-form",
        data={"name": "   Jason  ", "preference": "BOTH"},
    )
    assert response.status_code == 204
    body = client.get(f"/games/{code}").json()
    assert body["players"][0]["name"] == "Jason"


def test_add_player_form_rejects_blank_name(client):
    code = _create(client)
    response = client.post(
        f"/games/{code}/players-form",
        data={"name": "   ", "preference": "BOTH"},
    )
    assert response.status_code == 400


def test_add_player_form_html_input_has_maxlength_16(client):
    code = _create(client)
    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    assert 'maxlength="16"' in response.text


def test_add_player_form_uses_native_validation_bubble_on_duplicate(client):
    code = _create(client)
    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    assert "setCustomValidity" in response.text
    assert "reportValidity" in response.text
    assert "already in the game" in response.text


def test_setup_empty_state_hints_at_sharing_code(client):
    code = _create(client)
    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    assert "share the code with your team" in response.text


def test_setup_with_players_shows_tap_hint(client):
    code = _create(client)
    client.post(f"/games/{code}/players-form", data={"name": "Jason", "preference": "IF"})
    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    assert "Tap a player to edit or remove" in response.text


def test_setup_start_button_is_in_sticky_footer(client):
    code = _create(client)
    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    assert "fixed bottom-0" in response.text


def test_in_progress_scoreboard_shows_inning_and_lineup(client):
    code = _create(client)
    for i in range(1, 11):
        client.post(
            f"/games/{code}/players-form",
            data={"name": f"P{i}", "preference": "BOTH"},
        )
    client.post(f"/games/{code}/start")

    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    assert "1st Inning" in response.text
    assert "Next inning" in response.text
    assert ">P<" in response.text


def test_edit_player_form_updates_preference(client):
    code = _create(client)
    client.post(f"/games/{code}/players-form", data={"name": "Jason", "preference": "IF"})

    response = client.post(
        f"/games/{code}/players/Jason/edit-form",
        data={"preference": "BOTH"},
    )
    assert response.status_code == 204

    body = client.get(f"/games/{code}").json()
    player = body["players"][0]
    assert player["preference"] == "BOTH"


def test_lock_position_form_locks_player(client):
    code = _create(client)
    client.post(f"/games/{code}/players-form", data={"name": "Jason", "preference": "BOTH"})

    response = client.post(
        f"/games/{code}/locks-form/P",
        data={"player_name": "Jason"},
    )
    assert response.status_code == 204

    body = client.get(f"/games/{code}").json()
    assert body["locks"] == {"P": "Jason"}


def test_swap_form_swaps_field_player_with_bench(client):
    code = _create(client)
    for i in range(1, 12):
        client.post(
            f"/games/{code}/players-form",
            data={"name": f"P{i}", "preference": "BOTH"},
        )
    client.post(f"/games/{code}/start")

    body = client.get(f"/games/{code}").json()
    bench = body["last_assignment"]["bench"]
    benched = bench[0]
    target_pos = next(
        pos for pos, name in body["last_assignment"]["positions"].items()
        if name is not None and name != benched
    )

    response = client.post(
        f"/games/{code}/swap-form",
        data={"position": target_pos, "player_name": benched},
    )
    assert response.status_code == 204

    new_assignment = client.get(f"/games/{code}").json()["last_assignment"]
    assert new_assignment["positions"][target_pos] == benched


def test_in_progress_scoreboard_renders_action_panels(client):
    code = _create(client)
    for i in range(1, 12):
        client.post(
            f"/games/{code}/players-form",
            data={"name": f"P{i}", "preference": "BOTH"},
        )
    client.post(f"/games/{code}/start")

    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    text = response.text
    assert "/swap-form" in text
    assert "/locks-form/" in text
    assert "Swap with" in text
    assert "Lock " in text


def test_in_progress_scoreboard_shows_unlock_for_locked_position(client):
    code = _create(client)
    for i in range(1, 11):
        client.post(
            f"/games/{code}/players-form",
            data={"name": f"P{i}", "preference": "BOTH"},
        )
    client.put(f"/games/{code}/locks/P", json={"player_name": "P1"})
    client.post(f"/games/{code}/start")

    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    assert "Unlock" in response.text
    assert "Locked" in response.text
    assert f"hx-delete=\"/games/{code}/locks/P\"" in response.text


def test_in_progress_scoreboard_includes_edit_player_dropdown(client):
    code = _create(client)
    for i in range(1, 11):
        client.post(
            f"/games/{code}/players-form",
            data={"name": f"P{i}", "preference": "BOTH"},
        )
    client.post(f"/games/{code}/start")

    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    text = response.text
    assert ">Edit player<" in text
    assert f"manage-pick-{code}" in text
    assert f"manage-form-{code}-1" in text
    for i in range(1, 11):
        assert f"/players/P{i}/edit-form" in text
        assert f"hx-delete=\"/games/{code}/players/P{i}\"" in text


def test_end_button_uses_inline_yes_cancel_confirm(client):
    code = _create(client)
    client.post(f"/games/{code}/players-form", data={"name": "P1", "preference": "BOTH"})
    client.post(f"/games/{code}/start")

    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    text = response.text
    assert "hx-confirm" not in text
    assert "End the game now?" in text
    assert "Yes, end game" in text
    assert "Cancel" in text


def test_lock_position_mid_game_rewrites_last_assignment(client):
    code = _create(client)
    for i in range(1, 11):
        client.post(
            f"/games/{code}/players-form",
            data={"name": f"P{i}", "preference": "BOTH"},
        )
    client.post(f"/games/{code}/start")

    body = client.get(f"/games/{code}").json()
    positions = body["last_assignment"]["positions"]
    target_pos = "SS"
    incumbent = positions[target_pos]
    locked_player = next(
        name for pos, name in positions.items() if pos != target_pos and name
    )

    client.put(
        f"/games/{code}/locks/{target_pos}",
        json={"player_name": locked_player},
    )

    body = client.get(f"/games/{code}").json()
    new_positions = body["last_assignment"]["positions"]
    new_bench = body["last_assignment"]["bench"]

    assert new_positions[target_pos] == locked_player
    assert sum(1 for n in new_positions.values() if n == locked_player) == 1
    assert locked_player not in new_bench
    assert incumbent in new_bench or incumbent in new_positions.values()


def test_in_progress_player_remove_has_no_confirm_prompt(client):
    code = _create(client)
    for i in range(1, 11):
        client.post(
            f"/games/{code}/players-form",
            data={"name": f"P{i}", "preference": "BOTH"},
        )
    client.post(f"/games/{code}/start")

    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    text = response.text
    for i in range(1, 11):
        assert f"Remove {{ P{i} }}" not in text
    assert "hx-confirm=\"Remove" not in text


def test_bench_lock_form_locks_player_to_bench(client):
    code = _create(client)
    for i in range(1, 11):
        client.post(
            f"/games/{code}/players-form",
            data={"name": f"P{i}", "preference": "BOTH"},
        )
    client.post(f"/games/{code}/start")

    response = client.post(
        f"/games/{code}/bench-locks-form",
        data={"player_name": "P1"},
    )
    assert response.status_code == 204
    body = client.get(f"/games/{code}").json()
    assert "P1" in body["bench_locks"]
    assert "P1" in body["last_assignment"]["bench"]
    assert "P1" not in body["last_assignment"]["positions"].values()


def test_bench_locked_player_stays_on_bench_next_inning(client):
    code = _create(client)
    for i in range(1, 11):
        client.post(
            f"/games/{code}/players-form",
            data={"name": f"P{i}", "preference": "BOTH"},
        )
    client.post(f"/games/{code}/start")
    client.post(f"/games/{code}/bench-locks-form", data={"player_name": "P5"})
    client.post(f"/games/{code}/next-inning")
    client.post(f"/games/{code}/next-inning")

    body = client.get(f"/games/{code}").json()
    assert "P5" in body["last_assignment"]["bench"]
    assert "P5" not in body["last_assignment"]["positions"].values()


def test_unlock_bench_resets_stats_and_clears_lock(client):
    code = _create(client)
    for i in range(1, 11):
        client.post(
            f"/games/{code}/players-form",
            data={"name": f"P{i}", "preference": "BOTH"},
        )
    client.post(f"/games/{code}/start")
    client.post(f"/games/{code}/bench-locks-form", data={"player_name": "P5"})
    for _ in range(3):
        client.post(f"/games/{code}/next-inning")

    response = client.delete(f"/games/{code}/bench-locks/P5")
    assert response.status_code == 200
    body = response.json()
    assert "P5" not in body["bench_locks"]


def test_unlock_bench_returns_404_when_not_locked(client):
    code = _create(client)
    client.post(f"/games/{code}/players-form", data={"name": "P1", "preference": "BOTH"})
    client.post(f"/games/{code}/start")

    response = client.delete(f"/games/{code}/bench-locks/P1")
    assert response.status_code == 404


def test_bench_item_shows_lock_to_bench_when_unlocked(client):
    code = _create(client)
    for i in range(1, 12):
        client.post(
            f"/games/{code}/players-form",
            data={"name": f"P{i}", "preference": "BOTH"},
        )
    client.post(f"/games/{code}/start")

    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    text = response.text
    assert "Lock to bench" in text
    assert "/bench-locks-form" in text
    bench_section_start = text.find(">Bench<")
    bench_section_end = text.find("Add a player", bench_section_start)
    bench_section = text[bench_section_start:bench_section_end]
    assert "Save preference" not in bench_section


def test_bench_item_shows_unlock_when_locked(client):
    code = _create(client)
    for i in range(1, 12):
        client.post(
            f"/games/{code}/players-form",
            data={"name": f"P{i}", "preference": "BOTH"},
        )
    client.post(f"/games/{code}/start")
    body = client.get(f"/games/{code}").json()
    benched = body["last_assignment"]["bench"][0]
    client.post(f"/games/{code}/bench-locks-form", data={"player_name": benched})

    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    text = response.text
    assert "Unlock from bench" in text
    assert f"hx-delete=\"/games/{code}/bench-locks/{benched}\"" in text


def test_remove_player_strips_from_bench_locks(client):
    code = _create(client)
    for i in range(1, 11):
        client.post(
            f"/games/{code}/players-form",
            data={"name": f"P{i}", "preference": "BOTH"},
        )
    client.post(f"/games/{code}/start")
    client.post(f"/games/{code}/bench-locks-form", data={"player_name": "P5"})
    client.delete(f"/games/{code}/players/P5")

    body = client.get(f"/games/{code}").json()
    assert "P5" not in body["bench_locks"]


def test_bench_item_no_longer_has_remove_button(client):
    code = _create(client)
    for i in range(1, 12):
        client.post(
            f"/games/{code}/players-form",
            data={"name": f"P{i}", "preference": "BOTH"},
        )
    client.post(f"/games/{code}/start")

    body = client.get(f"/games/{code}").json()
    benched = body["last_assignment"]["bench"][0]

    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    text = response.text
    bench_section_start = text.find(">Bench<")
    assert bench_section_start != -1
    bench_section_end = text.find("Edit player", bench_section_start)
    bench_section = text[bench_section_start:bench_section_end]
    assert f"hx-delete=\"/games/{code}/players/{benched}\"" not in bench_section


def test_setup_scoreboard_shows_player_edit_and_remove_actions(client):
    code = _create(client)
    client.post(f"/games/{code}/players-form", data={"name": "Jason", "preference": "IF"})

    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    text = response.text
    assert f"/players/Jason/edit-form" in text
    assert f"hx-delete=\"/games/{code}/players/Jason\"" in text
    assert "Remove player" in text


def test_score_form_increments_team_score(client):
    code = _create(client)
    client.post(f"/games/{code}/players-form", data={"name": "P1", "preference": "BOTH"})
    client.post(f"/games/{code}/start")

    response = client.post(
        f"/games/{code}/score-form",
        data={"side": "us", "delta": "1"},
    )
    assert response.status_code == 204
    body = client.get(f"/games/{code}").json()
    assert body["team_score"] == 1
    assert body["opponent_score"] == 0


def test_score_form_increments_opponent_score(client):
    code = _create(client)
    client.post(f"/games/{code}/players-form", data={"name": "P1", "preference": "BOTH"})
    client.post(f"/games/{code}/start")

    for _ in range(3):
        client.post(f"/games/{code}/score-form", data={"side": "them", "delta": "1"})

    body = client.get(f"/games/{code}").json()
    assert body["opponent_score"] == 3
    assert body["team_score"] == 0


def test_score_form_decrements_but_clamps_at_zero(client):
    code = _create(client)
    client.post(f"/games/{code}/players-form", data={"name": "P1", "preference": "BOTH"})
    client.post(f"/games/{code}/start")

    client.post(f"/games/{code}/score-form", data={"side": "us", "delta": "1"})
    client.post(f"/games/{code}/score-form", data={"side": "us", "delta": "1"})
    client.post(f"/games/{code}/score-form", data={"side": "us", "delta": "-1"})
    client.post(f"/games/{code}/score-form", data={"side": "us", "delta": "-1"})
    client.post(f"/games/{code}/score-form", data={"side": "us", "delta": "-1"})

    body = client.get(f"/games/{code}").json()
    assert body["team_score"] == 0


def test_score_form_invalid_side_returns_400(client):
    code = _create(client)
    client.post(f"/games/{code}/players-form", data={"name": "P1", "preference": "BOTH"})
    client.post(f"/games/{code}/start")

    response = client.post(
        f"/games/{code}/score-form",
        data={"side": "neither", "delta": "1"},
    )
    assert response.status_code == 400


def test_in_progress_scoreboard_renders_ordinal_inning_and_score_widget(client):
    code = _create(client)
    for i in range(1, 11):
        client.post(
            f"/games/{code}/players-form",
            data={"name": f"P{i}", "preference": "BOTH"},
        )
    client.post(f"/games/{code}/start")
    client.post(f"/games/{code}/next-inning")
    client.post(f"/games/{code}/next-inning")

    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    text = response.text
    assert "3rd Inning" in text
    assert ">Us<" in text
    assert ">Opponents<" in text
    assert f"/games/{code}/score-form" in text


def test_in_progress_scoreboard_renders_2nd_for_inning_2(client):
    code = _create(client)
    client.post(f"/games/{code}/players-form", data={"name": "P1", "preference": "BOTH"})
    client.post(f"/games/{code}/start")
    client.post(f"/games/{code}/next-inning")

    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    assert "2nd Inning" in response.text


def test_ended_scoreboard_shows_final_score(client):
    code = _create(client)
    client.post(f"/games/{code}/players-form", data={"name": "P1", "preference": "BOTH"})
    client.post(f"/games/{code}/start")
    client.post(f"/games/{code}/score-form", data={"side": "us", "delta": "1"})
    client.post(f"/games/{code}/score-form", data={"side": "us", "delta": "1"})
    client.post(f"/games/{code}/score-form", data={"side": "them", "delta": "1"})
    client.post(f"/games/{code}/end")

    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    text = response.text
    assert "Final" in text
    assert ">2<" in text  # us
    assert ">1<" in text  # them


def test_ended_scoreboard_offers_next_game_and_end_for_day(client):
    code = _create(client)
    client.post(f"/games/{code}/players-form", data={"name": "P1", "preference": "BOTH"})
    client.post(f"/games/{code}/start")
    client.post(f"/games/{code}/end")

    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    text = response.text
    assert "Game 1 ended" in text
    assert "Go to Game 2" in text
    assert "End for the day" in text
    assert f"hx-post=\"/games/{code}/next-game\"" in text


def test_next_game_keeps_roster_resets_state_increments_counter(client):
    code = _create(client)
    for i in range(1, 11):
        client.post(
            f"/games/{code}/players-form",
            data={"name": f"P{i}", "preference": "BOTH"},
        )
    client.post(f"/games/{code}/start")
    client.post(f"/games/{code}/next-inning")
    client.post(f"/games/{code}/score-form", data={"side": "us", "delta": "5"})
    client.post(f"/games/{code}/score-form", data={"side": "them", "delta": "3"})
    client.post(f"/games/{code}/bench-locks-form", data={"player_name": "P3"})
    client.put(f"/games/{code}/locks/SS", json={"player_name": "P4"})
    client.post(f"/games/{code}/end")

    response = client.post(f"/games/{code}/next-game")
    assert response.status_code == 200

    body = client.get(f"/games/{code}").json()
    assert body["status"] == "setup"
    assert body["inning"] == 1
    assert body["team_score"] == 0
    assert body["opponent_score"] == 0
    assert body["games_played"] == 2
    assert body["last_assignment"] is None
    assert body["locks"] == {}
    assert body["bench_locks"] == []
    assert len(body["players"]) == 10
    for p in body["players"]:
        assert p["innings_played"] == 0
        assert p["innings_sat"] == 0
        assert p["current_play_streak"] == 0


def test_next_game_rejects_unless_ended(client):
    code = _create(client)
    client.post(f"/games/{code}/players-form", data={"name": "P1", "preference": "BOTH"})

    response = client.post(f"/games/{code}/next-game")
    assert response.status_code == 409


def test_setup_roster_header_shows_game_number_after_first_game(client):
    code = _create(client)
    client.post(f"/games/{code}/players-form", data={"name": "P1", "preference": "BOTH"})
    client.post(f"/games/{code}/start")
    client.post(f"/games/{code}/end")
    client.post(f"/games/{code}/next-game")

    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    assert "Game 2" in response.text


def test_ended_scoreboard_shows_correct_inning_after_advancing(client):
    code = _create(client)
    for i in range(1, 11):
        client.post(
            f"/games/{code}/players-form",
            data={"name": f"P{i}", "preference": "BOTH"},
        )
    client.post(f"/games/{code}/start")
    client.post(f"/games/{code}/next-inning")
    client.post(f"/games/{code}/next-inning")
    client.post(f"/games/{code}/next-inning")
    client.post(f"/games/{code}/end")

    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    assert "4th Inning" in response.text
    assert "3rd Inning" not in response.text


def test_ended_scoreboard_shows_end_message(client):
    code = _create(client)
    client.post(f"/games/{code}/players-form", data={"name": "Jason", "preference": "IF"})
    client.post(f"/games/{code}/start")
    client.post(f"/games/{code}/end")

    response = client.get(f"/games/{code}", headers={"Accept": "text/html"})
    assert "Game 1 ended" in response.text
    assert "End for the day" in response.text
