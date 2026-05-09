import pytest

from engine.models import GameState
from server.store import GAME_CODE_ALPHABET, GAME_CODE_LEN, GameStore


@pytest.fixture
def fake_clock():
    class Clock:
        def __init__(self):
            self.now = 1000.0

        def __call__(self):
            return self.now

    return Clock()


def test_create_returns_game_with_unique_code():
    store = GameStore()
    g1 = store.create(GameState(players=[]))
    g2 = store.create(GameState(players=[]))

    assert g1.code != g2.code
    assert len(g1.code) == GAME_CODE_LEN
    assert all(c in GAME_CODE_ALPHABET for c in g1.code)


def test_get_returns_game_by_code():
    store = GameStore()
    created = store.create(GameState(players=[]))
    fetched = store.get(created.code)
    assert fetched is created


def test_get_missing_code_returns_none():
    store = GameStore()
    assert store.get("ZZZZ") is None


def test_get_refreshes_idle_timer(fake_clock):
    store = GameStore(ttl_seconds=100, clock=fake_clock)
    game = store.create(GameState(players=[]))

    fake_clock.now = 1090.0
    assert store.get(game.code) is game

    fake_clock.now = 1180.0
    assert store.get(game.code) is game

    fake_clock.now = 1290.0
    assert store.get(game.code) is None


def test_sweep_evicts_idle_games(fake_clock):
    store = GameStore(ttl_seconds=100, clock=fake_clock)
    game = store.create(GameState(players=[]))

    fake_clock.now = 1200.0
    evicted = store.sweep()

    assert evicted == 1
    assert store.get(game.code) is None
    assert len(store) == 0


def test_update_persists_state_and_status(fake_clock):
    store = GameStore(clock=fake_clock)
    game = store.create(GameState(players=[]))

    new_state = GameState(players=[], inning=5)
    updated = store.update(game.code, new_state, status="in_progress")

    assert updated is not None
    assert updated.state.inning == 5
    assert updated.status == "in_progress"


def test_update_missing_code_returns_none():
    store = GameStore()
    assert store.update("ZZZZ", GameState(players=[])) is None
