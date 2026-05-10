import copy
from dataclasses import asdict

from fastapi import FastAPI, Form, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from engine.models import GameState, Player, Position, Preference
from engine.rotation import assign_inning
from engine.state import add_player as engine_add_player
from engine.state import apply_assignment, unlock_bench, unlock_position
from server.store import Game, GameStore
from server.ws import ConnectionManager

app = FastAPI(title="Softball Team Tracker")
app.mount("/static", StaticFiles(directory="web/static"), name="static")
store = GameStore()
ws_manager = ConnectionManager()
templates = Jinja2Templates(directory="web/templates")

PREFERENCE_LABELS = {
    "PITCHER": "Pitcher",
    "IF": "Infield",
    "OF": "Outfield",
    "BOTH": "Both",
}
templates.env.filters["pref_label"] = lambda p: PREFERENCE_LABELS.get(
    getattr(p, "value", str(p)), str(p)
)


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


templates.env.filters["ordinal"] = _ordinal


MAX_NAME_LENGTH = 16
MAX_SCORE = 99
MAX_INNING = 25
MAX_GAMES = 25


class AddPlayerRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=MAX_NAME_LENGTH)
    preference: Preference


class EditPlayerRequest(BaseModel):
    preference: Preference | None = None


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
        "team_score": game.state.team_score,
        "opponent_score": game.state.opponent_score,
        "team_name": game.state.team_name,
        "games_played": game.state.games_played,
        "players": [asdict(p) for p in game.state.players],
        "locks": {pos.value: name for pos, name in game.state.locks.items()},
        "bench_locks": list(game.state.bench_locks),
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


def _render_scoreboard(game_dict: dict) -> str:
    return templates.get_template("partials/scoreboard.html").render(game=game_dict)


def _get_game_or_404(code: str) -> Game:
    game = store.get(code.upper())
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


def _find_player(state: GameState, name: str) -> Player | None:
    return next((p for p in state.players if p.name == name), None)


async def _persist_and_broadcast(
    code: str, new_state: GameState, **kwargs
) -> dict:
    updated = store.update(code, new_state, **kwargs)
    assert updated is not None
    payload = _serialize_game(updated)
    await ws_manager.broadcast(updated.code, _render_scoreboard(payload))
    return payload


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, error: str | None = None):
    return templates.TemplateResponse(request, "index.html", {"error": error})


@app.post("/games/new")
async def create_game_form(team_name: str = Form(...)):
    cleaned = team_name.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Team name is required")
    if len(cleaned) > MAX_NAME_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Team name must be at most {MAX_NAME_LENGTH} characters",
        )
    game = store.create(GameState(players=[], team_name=cleaned))
    return RedirectResponse(url=f"/games/{game.code}", status_code=303)


@app.get("/join")
async def join_game(code: str):
    code = code.upper()
    if store.get(code) is None:
        return RedirectResponse(url="/?error=notfound", status_code=303)
    return RedirectResponse(url=f"/games/{code}", status_code=303)


@app.post("/games", status_code=201)
async def create_game():
    game = store.create(GameState(players=[]))
    return _serialize_game(game)


@app.get("/games/{code}")
async def game_page(request: Request, code: str):
    accept = request.headers.get("accept", "")
    game = _get_game_or_404(code)
    payload = _serialize_game(game)

    if "text/html" in accept:
        return templates.TemplateResponse(
            request, "game.html", {"game": payload}
        )
    return payload


@app.post("/games/{code}/players", status_code=201)
async def add_player(code: str, body: AddPlayerRequest):
    game = _get_game_or_404(code)
    if game.status == "ended":
        raise HTTPException(status_code=409, detail="Game has ended")
    if _find_player(game.state, body.name) is not None:
        raise HTTPException(status_code=409, detail="Player already in roster")

    new_player = Player(
        name=body.name,
        preference=body.preference,
    )

    if game.status == "setup":
        new_state = copy.deepcopy(game.state)
        new_state.players.append(new_player)
        return await _persist_and_broadcast(game.code, new_state)

    new_state = engine_add_player(game.state, new_player)
    if game.last_assignment is not None:
        new_assignment = copy.deepcopy(game.last_assignment)
        new_assignment.bench.append(new_player.name)
        return await _persist_and_broadcast(
            game.code, new_state, last_assignment=new_assignment
        )
    return await _persist_and_broadcast(game.code, new_state)


@app.post("/games/{code}/players-form", status_code=204)
async def add_player_form(
    code: str,
    name: str = Form(...),
    preference: Preference = Form(...),
):
    cleaned = name.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Name is required")
    if len(cleaned) > MAX_NAME_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Name must be at most {MAX_NAME_LENGTH} characters",
        )
    await add_player(
        code,
        AddPlayerRequest(name=cleaned, preference=preference),
    )
    return Response(status_code=204)


@app.post("/games/{code}/players/{name}/edit-form", status_code=204)
async def edit_player_form(
    code: str,
    name: str,
    preference: Preference = Form(...),
):
    await edit_player(code, name, EditPlayerRequest(preference=preference))
    return Response(status_code=204)


@app.post("/games/{code}/locks-form/{position}", status_code=204)
async def lock_position_form(
    code: str,
    position: Position,
    player_name: str = Form(...),
):
    await lock_position(code, position, LockRequest(player_name=player_name))
    return Response(status_code=204)


@app.post("/games/{code}/score-form", status_code=204)
async def score_form(
    code: str,
    side: str = Form(...),
    delta: int = Form(...),
):
    game = _get_game_or_404(code)
    if side not in ("us", "them"):
        raise HTTPException(status_code=400, detail="Invalid side")

    new_state = copy.deepcopy(game.state)
    if side == "us":
        new_state.team_score = min(MAX_SCORE, max(0, new_state.team_score + delta))
    else:
        new_state.opponent_score = min(MAX_SCORE, max(0, new_state.opponent_score + delta))

    await _persist_and_broadcast(game.code, new_state)
    return Response(status_code=204)


@app.post("/games/{code}/swap-form", status_code=204)
async def swap_form(
    code: str,
    position: Position = Form(...),
    player_name: str = Form(...),
):
    await swap(code, SwapRequest(position=position, player_name=player_name))
    return Response(status_code=204)


@app.delete("/games/{code}/players/{name}")
async def remove_player(code: str, name: str):
    game = _get_game_or_404(code)
    if _find_player(game.state, name) is None:
        raise HTTPException(status_code=404, detail="Player not in roster")

    new_state = copy.deepcopy(game.state)
    new_state.players = [p for p in new_state.players if p.name != name]
    new_state.locks = {pos: n for pos, n in new_state.locks.items() if n != name}
    new_state.bench_locks = [n for n in new_state.bench_locks if n != name]

    kwargs: dict = {}
    if game.last_assignment is not None:
        new_assignment = copy.deepcopy(game.last_assignment)
        new_assignment.positions = {
            pos: (None if n == name else n)
            for pos, n in new_assignment.positions.items()
        }
        new_assignment.bench = [n for n in new_assignment.bench if n != name]
        kwargs["last_assignment"] = new_assignment

    return await _persist_and_broadcast(game.code, new_state, **kwargs)


@app.patch("/games/{code}/players/{name}")
async def edit_player(code: str, name: str, body: EditPlayerRequest):
    game = _get_game_or_404(code)
    if _find_player(game.state, name) is None:
        raise HTTPException(status_code=404, detail="Player not in roster")

    new_state = copy.deepcopy(game.state)
    for player in new_state.players:
        if player.name == name:
            if body.preference is not None:
                player.preference = body.preference
            break

    return await _persist_and_broadcast(game.code, new_state)


@app.put("/games/{code}/locks/{position}")
async def lock_position(code: str, position: Position, body: LockRequest):
    game = _get_game_or_404(code)
    if _find_player(game.state, body.player_name) is None:
        raise HTTPException(status_code=404, detail="Player not in roster")

    new_state = copy.deepcopy(game.state)
    new_state.locks = {
        pos: name for pos, name in new_state.locks.items() if name != body.player_name
    }
    new_state.locks[position] = body.player_name
    new_state.bench_locks = [
        n for n in new_state.bench_locks if n != body.player_name
    ]

    kwargs: dict = {}
    if game.last_assignment is not None:
        new_assignment = copy.deepcopy(game.last_assignment)
        displaced = new_assignment.positions.get(position)
        new_assignment.positions = {
            pos: (None if n == body.player_name else n)
            for pos, n in new_assignment.positions.items()
        }
        new_assignment.bench = [
            n for n in new_assignment.bench if n != body.player_name
        ]
        new_assignment.positions[position] = body.player_name
        if displaced and displaced != body.player_name:
            new_assignment.bench.append(displaced)
        kwargs["last_assignment"] = new_assignment

    return await _persist_and_broadcast(game.code, new_state, **kwargs)


@app.delete("/games/{code}/locks/{position}")
async def unlock(code: str, position: Position):
    game = _get_game_or_404(code)
    if position not in game.state.locks:
        raise HTTPException(status_code=404, detail="Position not locked")

    new_state = unlock_position(game.state, position)
    return await _persist_and_broadcast(game.code, new_state)


@app.post("/games/{code}/bench-locks-form", status_code=204)
async def bench_lock_form(code: str, player_name: str = Form(...)):
    game = _get_game_or_404(code)
    if _find_player(game.state, player_name) is None:
        raise HTTPException(status_code=404, detail="Player not in roster")

    new_state = copy.deepcopy(game.state)
    if player_name not in new_state.bench_locks:
        new_state.bench_locks.append(player_name)
    new_state.locks = {
        pos: n for pos, n in new_state.locks.items() if n != player_name
    }

    kwargs: dict = {}
    if game.last_assignment is not None:
        new_assignment = copy.deepcopy(game.last_assignment)
        new_assignment.positions = {
            pos: (None if n == player_name else n)
            for pos, n in new_assignment.positions.items()
        }
        if player_name not in new_assignment.bench:
            new_assignment.bench.append(player_name)
        kwargs["last_assignment"] = new_assignment

    await _persist_and_broadcast(game.code, new_state, **kwargs)
    return Response(status_code=204)


@app.delete("/games/{code}/bench-locks/{name}")
async def unlock_bench_endpoint(code: str, name: str):
    game = _get_game_or_404(code)
    if name not in game.state.bench_locks:
        raise HTTPException(status_code=404, detail="Player not bench-locked")

    new_state = unlock_bench(game.state, name)
    return await _persist_and_broadcast(game.code, new_state)


@app.post("/games/{code}/start")
async def start_game(code: str):
    game = _get_game_or_404(code)
    if game.status != "setup":
        raise HTTPException(status_code=409, detail="Game already started")

    assignment = assign_inning(game.state)
    return await _persist_and_broadcast(
        game.code, game.state, status="in_progress", last_assignment=assignment
    )


@app.post("/games/{code}/next-inning")
async def next_inning(code: str):
    game = _get_game_or_404(code)
    if game.status != "in_progress":
        raise HTTPException(status_code=409, detail="Game is not in progress")
    if game.last_assignment is None:
        raise HTTPException(status_code=409, detail="No active inning to advance")
    if game.state.inning >= MAX_INNING:
        raise HTTPException(
            status_code=409,
            detail=f"Maximum {MAX_INNING} innings reached",
        )

    new_state = apply_assignment(game.state, game.last_assignment)
    next_assignment = assign_inning(new_state)
    return await _persist_and_broadcast(
        game.code, new_state, last_assignment=next_assignment
    )


@app.post("/games/{code}/end")
async def end_game(code: str):
    game = _get_game_or_404(code)
    if game.status == "ended":
        raise HTTPException(status_code=409, detail="Game already ended")

    return await _persist_and_broadcast(game.code, game.state, status="ended")


@app.post("/games/{code}/next-game")
async def next_game(code: str):
    game = _get_game_or_404(code)
    if game.status != "ended":
        raise HTTPException(
            status_code=409,
            detail="Current game is not ended",
        )
    if game.state.games_played >= MAX_GAMES:
        raise HTTPException(
            status_code=409,
            detail=f"Maximum {MAX_GAMES} games reached",
        )

    new_state = copy.deepcopy(game.state)
    new_state.inning = 1
    new_state.team_score = 0
    new_state.opponent_score = 0
    new_state.locks = {}
    new_state.bench_locks = []
    new_state.games_played += 1
    for player in new_state.players:
        player.innings_played = 0
        player.innings_sat = 0
        player.current_play_streak = 0
        player.last_inning_at = {}

    return await _persist_and_broadcast(
        game.code,
        new_state,
        status="setup",
        last_assignment=None,
    )


@app.post("/games/{code}/swap")
async def swap(code: str, body: SwapRequest):
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
    return await _persist_and_broadcast(
        game.code, game.state, last_assignment=new_assignment
    )


@app.websocket("/ws/{code}")
async def ws_game(websocket: WebSocket, code: str):
    code = code.upper()
    game = store.get(code)
    if game is None:
        await websocket.close(code=4404)
        return

    await ws_manager.connect(code, websocket)
    try:
        await websocket.send_text(_render_scoreboard(_serialize_game(game)))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(code, websocket)
