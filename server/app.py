import copy
from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from engine.models import GameState, Player, Position, Preference
from engine.rotation import assign_inning
from engine.state import add_player as engine_add_player
from engine.state import apply_assignment, unlock_position
from server.store import Game, GameStore

app = FastAPI(title="Softball Rotation")
store = GameStore()


class AddPlayerRequest(BaseModel):
    name: str
    preference: Preference
    never_pitch: bool = False


class EditPlayerRequest(BaseModel):
    preference: Preference | None = None
    never_pitch: bool | None = None


class LockRequest(BaseModel):
    player_name: str


class SwapRequest(BaseModel):
    position: Position
    player_name: str


def _serialize_game(game: Game) -> dict:
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


def _get_game_or_404(code: str) -> Game:
    game = store.get(code.upper())
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


def _find_player(state: GameState, name: str) -> Player | None:
    return next((p for p in state.players if p.name == name), None)


def _persist(code: str, new_state: GameState, **kwargs) -> Game:
    updated = store.update(code, new_state, **kwargs)
    assert updated is not None
    return updated


@app.post("/games", status_code=201)
def create_game():
    game = store.create(GameState(players=[]))
    return _serialize_game(game)


@app.get("/games/{code}")
def get_game(code: str):
    return _serialize_game(_get_game_or_404(code))


@app.post("/games/{code}/players", status_code=201)
def add_player(code: str, body: AddPlayerRequest):
    game = _get_game_or_404(code)
    if game.status == "ended":
        raise HTTPException(status_code=409, detail="Game has ended")
    if _find_player(game.state, body.name) is not None:
        raise HTTPException(status_code=409, detail="Player already in roster")

    new_player = Player(
        name=body.name,
        preference=body.preference,
        never_pitch=body.never_pitch,
    )

    if game.status == "setup":
        new_state = copy.deepcopy(game.state)
        new_state.players.append(new_player)
    else:
        new_state = engine_add_player(game.state, new_player)

    return _serialize_game(_persist(game.code, new_state))


@app.delete("/games/{code}/players/{name}")
def remove_player(code: str, name: str):
    game = _get_game_or_404(code)
    if _find_player(game.state, name) is None:
        raise HTTPException(status_code=404, detail="Player not in roster")

    new_state = copy.deepcopy(game.state)
    new_state.players = [p for p in new_state.players if p.name != name]
    new_state.locks = {pos: n for pos, n in new_state.locks.items() if n != name}

    return _serialize_game(_persist(game.code, new_state))


@app.patch("/games/{code}/players/{name}")
def edit_player(code: str, name: str, body: EditPlayerRequest):
    game = _get_game_or_404(code)
    if _find_player(game.state, name) is None:
        raise HTTPException(status_code=404, detail="Player not in roster")

    new_state = copy.deepcopy(game.state)
    for player in new_state.players:
        if player.name == name:
            if body.preference is not None:
                player.preference = body.preference
            if body.never_pitch is not None:
                player.never_pitch = body.never_pitch
            break

    return _serialize_game(_persist(game.code, new_state))


@app.put("/games/{code}/locks/{position}")
def lock_position(code: str, position: Position, body: LockRequest):
    game = _get_game_or_404(code)
    if _find_player(game.state, body.player_name) is None:
        raise HTTPException(status_code=404, detail="Player not in roster")

    new_state = copy.deepcopy(game.state)
    new_state.locks = {
        pos: name for pos, name in new_state.locks.items() if name != body.player_name
    }
    new_state.locks[position] = body.player_name

    return _serialize_game(_persist(game.code, new_state))


@app.delete("/games/{code}/locks/{position}")
def unlock(code: str, position: Position):
    game = _get_game_or_404(code)
    if position not in game.state.locks:
        raise HTTPException(status_code=404, detail="Position not locked")

    new_state = unlock_position(game.state, position)
    return _serialize_game(_persist(game.code, new_state))


@app.post("/games/{code}/start")
def start_game(code: str):
    game = _get_game_or_404(code)
    if game.status != "setup":
        raise HTTPException(status_code=409, detail="Game already started")

    assignment = assign_inning(game.state)
    return _serialize_game(
        _persist(game.code, game.state, status="in_progress", last_assignment=assignment)
    )


@app.post("/games/{code}/next-inning")
def next_inning(code: str):
    game = _get_game_or_404(code)
    if game.status != "in_progress":
        raise HTTPException(status_code=409, detail="Game is not in progress")
    if game.last_assignment is None:
        raise HTTPException(status_code=409, detail="No active inning to advance")

    new_state = apply_assignment(game.state, game.last_assignment)
    next_assignment = assign_inning(new_state)
    return _serialize_game(
        _persist(game.code, new_state, last_assignment=next_assignment)
    )


@app.post("/games/{code}/end")
def end_game(code: str):
    game = _get_game_or_404(code)
    if game.status == "ended":
        raise HTTPException(status_code=409, detail="Game already ended")

    return _serialize_game(_persist(game.code, game.state, status="ended"))


@app.post("/games/{code}/swap")
def swap(code: str, body: SwapRequest):
    game = _get_game_or_404(code)
    if game.status != "in_progress":
        raise HTTPException(status_code=409, detail="Game is not in progress")
    if game.last_assignment is None:
        raise HTTPException(status_code=409, detail="No active inning")
    if body.position in game.state.locks:
        raise HTTPException(
            status_code=409, detail="Cannot swap into a locked position"
        )
    if _find_player(game.state, body.player_name) is None:
        raise HTTPException(status_code=404, detail="Player not in roster")
    if body.player_name in game.state.locks.values():
        raise HTTPException(status_code=409, detail="Player is locked elsewhere")

    new_assignment = copy.deepcopy(game.last_assignment)
    positions = new_assignment.positions
    bench = list(new_assignment.bench)

    current_at_target = positions[body.position]
    if current_at_target == body.player_name:
        return _serialize_game(game)

    other_position = next(
        (pos for pos, name in positions.items() if name == body.player_name),
        None,
    )

    if other_position is not None:
        positions[body.position] = body.player_name
        positions[other_position] = current_at_target
    else:
        if body.player_name in bench:
            bench.remove(body.player_name)
        positions[body.position] = body.player_name
        if current_at_target is not None:
            bench.append(current_at_target)

    new_assignment.bench = bench
    return _serialize_game(
        _persist(game.code, game.state, last_assignment=new_assignment)
    )
