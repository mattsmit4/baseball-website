from dataclasses import asdict

from fastapi import FastAPI, HTTPException

from engine.models import GameState
from server.store import GameStore

app = FastAPI(title="Softball Rotation")
store = GameStore()


def _serialize_game(game) -> dict:
    return {
        "code": game.code,
        "status": game.status,
        "inning": game.state.inning,
        "players": [asdict(p) for p in game.state.players],
        "locks": {pos.value: name for pos, name in game.state.locks.items()},
        "last_assignment": (
            {
                "inning": game.last_assignment.inning,
                "positions": {
                    pos.value: name
                    for pos, name in game.last_assignment.positions.items()
                },
                "bench": list(game.last_assignment.bench),
            }
            if game.last_assignment is not None
            else None
        ),
    }


@app.post("/games", status_code=201)
def create_game():
    game = store.create(GameState(players=[]))
    return _serialize_game(game)


@app.get("/games/{code}")
def get_game(code: str):
    game = store.get(code.upper())
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    return _serialize_game(game)
