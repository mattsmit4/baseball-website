from dataclasses import dataclass, field
from enum import Enum


class Preference(str, Enum):
    PITCHER = "PITCHER"
    INFIELD = "IF"
    OUTFIELD = "OF"
    BOTH = "BOTH"


class Position(str, Enum):
    PITCHER = "P"
    CATCHER = "C"
    FIRST = "1B"
    SECOND = "2B"
    SHORTSTOP = "SS"
    THIRD = "3B"
    LEFT = "LF"
    LEFT_CENTER = "LCF"
    RIGHT_CENTER = "RCF"
    RIGHT = "RF"


@dataclass
class Player:
    name: str
    preference: Preference
    innings_played: int = 0
    innings_sat: int = 0
    current_play_streak: int = 0
    last_inning_at: dict["Position", int] = field(default_factory=dict)


@dataclass
class GameState:
    players: list[Player]
    locks: dict[Position, str] = field(default_factory=dict)
    bench_locks: list[str] = field(default_factory=list)
    inning: int = 1
    team_score: int = 0
    opponent_score: int = 0
    team_name: str = "Us"
    games_played: int = 1


@dataclass
class InningAssignment:
    inning: int
    positions: dict[Position, str | None]
    bench: list[str]
