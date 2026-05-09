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
    if player.preference == Preference.PITCHER:
        return position == Position.PITCHER
    if position == Position.PITCHER:
        return not player.never_pitch
    if position in INFIELD_POSITIONS:
        return player.preference in (Preference.INFIELD, Preference.BOTH)
    if position in OUTFIELD_POSITIONS:
        return player.preference in (Preference.OUTFIELD, Preference.BOTH)
    return False


def _max_matching(
    players: list[Player], positions: list[Position]
) -> dict[Position, str]:
    """Bipartite max matching via augmenting paths. Within each player's
    eligible positions, prefers the one they've played least recently — gives
    soft position variety as a tiebreaker."""
    pos_to_player: dict[Position, Player] = {}

    def augment(player: Player, visited: set[Position]) -> bool:
        eligible = sorted(
            (
                pos
                for pos in positions
                if _is_eligible(player, pos) and pos not in visited
            ),
            key=lambda pos: player.last_inning_at.get(pos, 0),
        )
        for pos in eligible:
            visited.add(pos)
            if pos not in pos_to_player or augment(pos_to_player[pos], visited):
                pos_to_player[pos] = player
                return True
        return False

    for player in players:
        augment(player, set())

    return {pos: p.name for pos, p in pos_to_player.items()}


def assign_inning(state: GameState) -> InningAssignment:
    locked_names = set(state.locks.values())
    open_positions = [p for p in Position if p not in state.locks]
    pool = [p for p in state.players if p.name not in locked_names]

    pitcher_assignment: Player | None = None
    if Position.PITCHER in open_positions:
        pitcher_prefs = [p for p in pool if p.preference == Preference.PITCHER]
        if pitcher_prefs:
            pitcher_assignment = min(
                pitcher_prefs,
                key=lambda p: (p.innings_played - p.innings_sat, p.current_play_streak),
            )

    if pitcher_assignment is not None:
        remaining_pool = [p for p in pool if p.name != pitcher_assignment.name]
        remaining_positions = [p for p in open_positions if p != Position.PITCHER]
    else:
        remaining_pool = pool
        remaining_positions = open_positions

    sorted_pool = sorted(
        remaining_pool,
        key=lambda p: (p.innings_played - p.innings_sat, p.current_play_streak),
        reverse=True,
    )

    max_fillable = len(_max_matching(sorted_pool, remaining_positions))
    excess = len(sorted_pool) - max_fillable

    bench: list[Player] = []
    playing = list(sorted_pool)

    if excess > 0:
        for candidate in sorted_pool:
            if len(bench) >= excess:
                break
            trial = [p for p in playing if p.name != candidate.name]
            if len(_max_matching(trial, remaining_positions)) == max_fillable:
                bench.append(candidate)
                playing = trial

    matching = _max_matching(playing, remaining_positions)

    positions_filled: dict[Position, str | None] = {p: None for p in Position}
    for pos, name in state.locks.items():
        positions_filled[pos] = name
    if pitcher_assignment is not None:
        positions_filled[Position.PITCHER] = pitcher_assignment.name
    for pos, name in matching.items():
        positions_filled[pos] = name

    return InningAssignment(
        inning=state.inning,
        positions=positions_filled,
        bench=[p.name for p in bench],
    )
