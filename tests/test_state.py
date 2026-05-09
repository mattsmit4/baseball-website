from engine.models import GameState, InningAssignment, Player, Position, Preference
from engine.state import add_player, apply_assignment, unlock_position


def test_apply_assignment_updates_counts_streaks_position_history_and_inning():
    """After apply_assignment:
    - played players: +1 innings_played, +1 current_play_streak, last_inning_at updated
    - benched players: +1 innings_sat, current_play_streak reset to 0
    - inning counter bumps by 1"""
    alice = Player(
        name="Alice",
        preference=Preference.BOTH,
        innings_played=2,
        innings_sat=1,
        current_play_streak=2,
    )
    bob = Player(
        name="Bob",
        preference=Preference.BOTH,
        innings_played=1,
        innings_sat=2,
        current_play_streak=0,
    )
    state = GameState(players=[alice, bob], inning=4)

    positions = {p: None for p in Position}
    positions[Position.SHORTSTOP] = "Alice"
    assignment = InningAssignment(inning=4, positions=positions, bench=["Bob"])

    new_state = apply_assignment(state, assignment)

    new_alice = next(p for p in new_state.players if p.name == "Alice")
    assert new_alice.innings_played == 3
    assert new_alice.innings_sat == 1
    assert new_alice.current_play_streak == 3
    assert new_alice.last_inning_at[Position.SHORTSTOP] == 4

    new_bob = next(p for p in new_state.players if p.name == "Bob")
    assert new_bob.innings_played == 1
    assert new_bob.innings_sat == 3
    assert new_bob.current_play_streak == 0

    assert new_state.inning == 5


def test_late_joiner_inherits_team_average_play_and_sit_counts():
    """A new player added mid-game gets innings_played and innings_sat
    initialized to the rounded team average, so they slot into the
    rotation fairly without being over- or under-prioritized."""
    veterans = [
        Player(name="V1", preference=Preference.BOTH, innings_played=4, innings_sat=2),
        Player(name="V2", preference=Preference.BOTH, innings_played=4, innings_sat=2),
    ]
    state = GameState(players=veterans, inning=7)

    new_state = add_player(state, Player(name="Latecomer", preference=Preference.BOTH))

    latecomer = next(p for p in new_state.players if p.name == "Latecomer")
    assert latecomer.innings_played == 4
    assert latecomer.innings_sat == 2


def test_unlocking_position_resets_player_stats_to_pool_average():
    """When a locked player is unlocked, their stats reset to the rotation
    pool's average so they don't get overplayed catching up after dominating
    one slot for many innings."""
    pool = [
        Player(name="P1", preference=Preference.BOTH, innings_played=2, innings_sat=4),
        Player(name="P2", preference=Preference.BOTH, innings_played=2, innings_sat=4),
    ]
    jason = Player(
        name="Jason",
        preference=Preference.BOTH,
        innings_played=6,
        innings_sat=0,
    )
    state = GameState(
        players=[jason, *pool],
        locks={Position.PITCHER: "Jason"},
        inning=7,
    )

    new_state = unlock_position(state, Position.PITCHER)

    new_jason = next(p for p in new_state.players if p.name == "Jason")
    assert new_jason.innings_played == 2
    assert new_jason.innings_sat == 4
    assert Position.PITCHER not in new_state.locks
