import copy

from engine.models import GameState, InningAssignment, Player, Position


def add_player(state: GameState, new_player: Player) -> GameState:
    """Add a player mid-game. Their innings_played and innings_sat are seeded
    to the rounded team average over the current rotation pool (excluding any
    locked players), so the late joiner is treated fairly going forward."""
    new_state = copy.deepcopy(state)
    locked_names = set(new_state.locks.values())
    pool = [p for p in new_state.players if p.name not in locked_names]

    if pool:
        avg_played = round(sum(p.innings_played for p in pool) / len(pool))
        avg_sat = round(sum(p.innings_sat for p in pool) / len(pool))
    else:
        avg_played = 0
        avg_sat = 0

    seeded = copy.deepcopy(new_player)
    seeded.innings_played = avg_played
    seeded.innings_sat = avg_sat
    new_state.players.append(seeded)
    return new_state


def unlock_bench(state: GameState, name: str) -> GameState:
    """Remove a bench lock and reset that player's innings_played /
    innings_sat to the rotation pool average, so they don't get over-played
    catching up after sitting out."""
    new_state = copy.deepcopy(state)
    if name not in new_state.bench_locks:
        return new_state

    new_state.bench_locks = [n for n in new_state.bench_locks if n != name]
    locked_names = set(new_state.locks.values()) | set(new_state.bench_locks)
    pool = [
        p for p in new_state.players
        if p.name not in locked_names and p.name != name
    ]

    if pool:
        avg_played = round(sum(p.innings_played for p in pool) / len(pool))
        avg_sat = round(sum(p.innings_sat for p in pool) / len(pool))
    else:
        avg_played = 0
        avg_sat = 0

    for player in new_state.players:
        if player.name == name:
            player.innings_played = avg_played
            player.innings_sat = avg_sat
            break

    return new_state


def unlock_position(state: GameState, position: Position) -> GameState:
    """Remove a position lock and reset the unlocked player's innings_played /
    innings_sat to the rotation pool average, so they don't get over-benched
    catching up after being locked at one position."""
    new_state = copy.deepcopy(state)
    if position not in new_state.locks:
        return new_state

    unlocked_name = new_state.locks.pop(position)
    other_locked_names = set(new_state.locks.values())
    pool = [
        p for p in new_state.players
        if p.name not in other_locked_names and p.name != unlocked_name
    ]

    if pool:
        avg_played = round(sum(p.innings_played for p in pool) / len(pool))
        avg_sat = round(sum(p.innings_sat for p in pool) / len(pool))
    else:
        avg_played = 0
        avg_sat = 0

    for player in new_state.players:
        if player.name == unlocked_name:
            player.innings_played = avg_played
            player.innings_sat = avg_sat
            break

    return new_state


def apply_assignment(state: GameState, assignment: InningAssignment) -> GameState:
    new_state = copy.deepcopy(state)

    played_at = {
        name: position
        for position, name in assignment.positions.items()
        if name is not None
    }
    bench_set = set(assignment.bench)

    for player in new_state.players:
        if player.name in played_at:
            player.innings_played += 1
            player.current_play_streak += 1
            player.last_inning_at[played_at[player.name]] = assignment.inning
        elif player.name in bench_set:
            player.innings_sat += 1
            player.current_play_streak = 0
            player.sit_history.append(assignment.inning)

    new_state.inning = state.inning + 1
    return new_state
