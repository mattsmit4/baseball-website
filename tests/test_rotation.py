from engine.models import GameState, Player, Position, Preference
from engine.rotation import assign_inning

INFIELD_POSITIONS = {
    Position.CATCHER,
    Position.FIRST,
    Position.SECOND,
    Position.SHORTSTOP,
    Position.THIRD,
}


def test_single_both_player_is_assigned_to_a_position():
    """Tracer bullet: with one BOTH-preference player and no locks,
    that player ends up filling exactly one position and isn't on the bench."""
    state = GameState(
        players=[Player(name="Alice", preference=Preference.BOTH)],
    )

    assignment = assign_inning(state)

    positions_for_alice = [pos for pos, name in assignment.positions.items() if name == "Alice"]
    assert len(positions_for_alice) == 1
    assert "Alice" not in assignment.bench


def test_never_pitch_player_is_not_assigned_to_pitcher():
    """A player with never_pitch=True is never placed at the pitcher slot."""
    state = GameState(
        players=[
            Player(name="NoPitcher", preference=Preference.BOTH, never_pitch=True),
            Player(name="Bothy", preference=Preference.BOTH),
        ]
    )

    assignment = assign_inning(state)

    assert assignment.positions[Position.PITCHER] != "NoPitcher"


def test_outfield_only_player_never_assigned_to_infield():
    """A player with OUTFIELD preference is never placed at an infield position.
    Pitcher is preference-agnostic so it's allowed."""
    state = GameState(
        players=[
            Player(name="Bothy", preference=Preference.BOTH),
            Player(name="Olivia", preference=Preference.OUTFIELD),
        ]
    )

    assignment = assign_inning(state)

    olivia_position = next(
        (pos for pos, name in assignment.positions.items() if name == "Olivia"),
        None,
    )
    assert olivia_position is not None, "Olivia should be playing somewhere"
    assert olivia_position not in INFIELD_POSITIONS


def test_position_variety_avoids_player_who_recently_played_position():
    """Among multiple eligible players, the algorithm picks the one who played
    that position least recently. A player who just played SS shouldn't get SS
    again if another eligible player has a longer gap."""
    quinn = Player(name="Quinn", preference=Preference.BOTH)
    pat = Player(
        name="Pat",
        preference=Preference.BOTH,
        last_inning_at={Position.SHORTSTOP: 4},
    )
    riley = Player(name="Riley", preference=Preference.BOTH)
    dummies = [Player(name=f"Lock{i}", preference=Preference.BOTH) for i in range(1, 8)]
    locks = {
        Position.PITCHER: "Lock1",
        Position.CATCHER: "Lock2",
        Position.SECOND: "Lock3",
        Position.LEFT: "Lock4",
        Position.LEFT_CENTER: "Lock5",
        Position.RIGHT_CENTER: "Lock6",
        Position.RIGHT: "Lock7",
    }
    state = GameState(
        players=[quinn, pat, riley, *dummies],
        locks=locks,
        inning=5,
    )

    assignment = assign_inning(state)

    assert assignment.positions[Position.SHORTSTOP] != "Pat", (
        "Pat just played SS in inning 4 — algorithm should pick Riley (no SS history)"
    )


def test_fewer_players_than_positions_leaves_unfilled_slots_as_none():
    """With fewer players than the 10 positions, unfilled slots stay None
    and nobody is benched."""
    players = [Player(name=f"Player{i}", preference=Preference.BOTH) for i in range(6)]
    state = GameState(players=players)

    assignment = assign_inning(state)

    filled = sum(1 for name in assignment.positions.values() if name is not None)
    unfilled = sum(1 for name in assignment.positions.values() if name is None)
    assert filled == 6
    assert unfilled == 4
    assert assignment.bench == []


def test_locked_player_stays_at_locked_position_and_is_not_benched():
    """A player locked at a position is placed there and isn't in the rotation pool —
    even if their play stats would otherwise put them on the bench."""
    jason = Player(
        name="Jason",
        preference=Preference.BOTH,
        innings_played=10,
        innings_sat=0,
    )
    rookies = [Player(name=f"Rookie{i}", preference=Preference.BOTH) for i in range(10)]
    state = GameState(
        players=[jason, *rookies],
        locks={Position.PITCHER: "Jason"},
    )

    assignment = assign_inning(state)

    assert assignment.positions[Position.PITCHER] == "Jason"
    assert "Jason" not in assignment.bench


def test_streak_breaks_tie_when_play_minus_sit_equal():
    """Two players with the same play_minus_sit but different current_play_streak —
    the one with the longer streak sits first."""
    short_streak = Player(
        name="ShortStreak",
        preference=Preference.BOTH,
        innings_played=5,
        innings_sat=2,
        current_play_streak=1,
    )
    long_streak = Player(
        name="LongStreak",
        preference=Preference.BOTH,
        innings_played=3,
        innings_sat=0,
        current_play_streak=3,
    )
    rookies = [Player(name=f"Rookie{i}", preference=Preference.BOTH) for i in range(9)]
    state = GameState(players=[short_streak, long_streak, *rookies])

    assignment = assign_inning(state)

    assert "LongStreak" in assignment.bench
    assert "ShortStreak" not in assignment.bench


def test_most_played_player_is_benched_when_pool_exceeds_slots():
    """With 11 BOTH players and no locks, the player with the highest
    play_minus_sit (most innings played relative to sat) is on the bench."""
    veteran = Player(
        name="Veteran",
        preference=Preference.BOTH,
        innings_played=5,
        innings_sat=0,
    )
    rookies = [Player(name=f"Rookie{i}", preference=Preference.BOTH) for i in range(10)]
    state = GameState(players=[veteran, *rookies])

    assignment = assign_inning(state)

    assert "Veteran" in assignment.bench
    assert "Veteran" not in assignment.positions.values()


def test_pitcher_preference_player_only_eligible_for_pitcher():
    """A player with PITCHER preference only plays pitcher. With one PITCHER
    and ten BOTH players (11 total), the PITCHER takes the mound and one BOTH
    player sits."""
    pitcher = Player(name="Pitcher", preference=Preference.PITCHER)
    others = [Player(name=f"Both{i}", preference=Preference.BOTH) for i in range(10)]
    state = GameState(players=[pitcher, *others])

    assignment = assign_inning(state)

    assert assignment.positions[Position.PITCHER] == "Pitcher"
    assert "Pitcher" not in assignment.bench
    pitcher_other_positions = [
        pos for pos, name in assignment.positions.items()
        if name == "Pitcher" and pos != Position.PITCHER
    ]
    assert pitcher_other_positions == []


def test_pitcher_preference_player_sits_when_pitcher_is_locked():
    """A PITCHER-preference player has no eligible position when pitcher is
    already locked to someone else, so they sit."""
    pitcher_pref = Player(name="Pitchy", preference=Preference.PITCHER)
    locked_pitcher = Player(name="Locked", preference=Preference.BOTH)
    others = [Player(name=f"Both{i}", preference=Preference.BOTH) for i in range(9)]
    state = GameState(
        players=[pitcher_pref, locked_pitcher, *others],
        locks={Position.PITCHER: "Locked"},
    )

    assignment = assign_inning(state)

    assert assignment.positions[Position.PITCHER] == "Locked"
    assert "Pitchy" in assignment.bench


def test_outfield_only_players_are_never_benched_when_their_slots_need_filling():
    """The reported bug: with 14 players (10 IF + 4 OF) the only eligible OF
    pool is the 4 OF-preference players, so all four must always play OF.
    The 4 bench spots come from the IF surplus, not from OF."""
    of_players = [
        Player(name=f"OF{i}", preference=Preference.OUTFIELD, innings_played=10, innings_sat=0)
        for i in range(4)
    ]
    if_players = [
        Player(name=f"IF{i}", preference=Preference.INFIELD)
        for i in range(10)
    ]
    state = GameState(players=[*of_players, *if_players])

    assignment = assign_inning(state)

    of_names = {p.name for p in of_players}
    benched_of = of_names & set(assignment.bench)
    assert benched_of == set(), f"OF-only players were benched: {benched_of}"

    for of_pos in (Position.LEFT, Position.LEFT_CENTER, Position.RIGHT_CENTER, Position.RIGHT):
        assert assignment.positions[of_pos] in of_names, (
            f"{of_pos} should be filled by one of the four OF players"
        )

    assert len(assignment.bench) == 4
    assert all(name.startswith("IF") for name in assignment.bench)


def test_no_blank_positions_when_pool_can_cover_all_ten():
    """With 14 players where every position has at least one eligible player,
    no slot should be left blank."""
    of_players = [Player(name=f"OF{i}", preference=Preference.OUTFIELD) for i in range(4)]
    if_players = [Player(name=f"IF{i}", preference=Preference.INFIELD) for i in range(10)]
    state = GameState(players=[*of_players, *if_players])

    assignment = assign_inning(state)

    unfilled = [pos for pos, name in assignment.positions.items() if name is None]
    assert unfilled == []


def test_unfillable_positions_remain_blank_when_no_eligible_player_exists():
    """With 12 IF-preference players (zero OF-eligible), the 4 outfield slots
    cannot be filled — they stay blank, and the bench size reflects the
    actually-fillable headcount."""
    if_players = [Player(name=f"IF{i}", preference=Preference.INFIELD) for i in range(12)]
    state = GameState(players=if_players)

    assignment = assign_inning(state)

    of_positions = (Position.LEFT, Position.LEFT_CENTER, Position.RIGHT_CENTER, Position.RIGHT)
    for pos in of_positions:
        assert assignment.positions[pos] is None

    filled = sum(1 for name in assignment.positions.values() if name is not None)
    assert filled == 6
    assert len(assignment.bench) == 12 - 6
