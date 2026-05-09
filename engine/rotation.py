from engine.models import GameState, InningAssignment, Player, Position, Preference

INFIELD_POSITIONS = {
    Position.CATCHER,
    Position.FIRST,
    Position.SECOND,
    Position.SHORTSTOP,
    Position.THIRD,
}
OUTFIELD_POSITIONS = {
    Position.LEFT,
    Position.LEFT_CENTER,
    Position.RIGHT_CENTER,
    Position.RIGHT,
}


def _is_eligible(player: Player, position: Position) -> bool:
    if position == Position.PITCHER:
        return not player.never_pitch
    if position in INFIELD_POSITIONS:
        return player.preference in (Preference.INFIELD, Preference.BOTH)
    if position in OUTFIELD_POSITIONS:
        return player.preference in (Preference.OUTFIELD, Preference.BOTH)
    return False


def assign_inning(state: GameState) -> InningAssignment:
    positions: dict[Position, str | None] = {p: None for p in Position}

    locked_names = set(state.locks.values())
    for position, player_name in state.locks.items():
        positions[position] = player_name

    open_positions = [p for p in Position if p not in state.locks]
    rotation_pool = [p for p in state.players if p.name not in locked_names]

    sorted_players = sorted(
        rotation_pool,
        key=lambda p: (p.innings_played - p.innings_sat, p.current_play_streak),
        reverse=True,
    )

    excess = len(sorted_players) - len(open_positions)
    if excess > 0:
        bench = [p.name for p in sorted_players[:excess]]
        playing = list(sorted_players[excess:])
    else:
        bench = []
        playing = list(sorted_players)

    for position in open_positions:
        eligible = [p for p in playing if _is_eligible(p, position)]
        if not eligible:
            continue
        chosen = min(eligible, key=lambda p: p.last_inning_at.get(position, 0))
        positions[position] = chosen.name
        playing.remove(chosen)

    return InningAssignment(inning=state.inning, positions=positions, bench=bench)
