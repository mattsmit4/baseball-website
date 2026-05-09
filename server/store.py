import secrets
import string
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable

from engine.models import GameState, InningAssignment

GAME_CODE_LEN = 4
GAME_CODE_ALPHABET = string.ascii_uppercase
IDLE_TTL_SECONDS = 12 * 60 * 60


@dataclass
class Game:
    code: str
    state: GameState
    status: str = "setup"
    last_assignment: InningAssignment | None = None
    last_touched_at: float = field(default_factory=time.monotonic)


class GameStore:
    def __init__(
        self,
        ttl_seconds: float = IDLE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._games: dict[str, Game] = {}
        self._lock = Lock()
        self._ttl = ttl_seconds
        self._clock = clock

    def _generate_code(self) -> str:
        while True:
            code = "".join(
                secrets.choice(GAME_CODE_ALPHABET) for _ in range(GAME_CODE_LEN)
            )
            if code not in self._games:
                return code

    def create(self, state: GameState) -> Game:
        with self._lock:
            self._sweep_locked()
            code = self._generate_code()
            game = Game(code=code, state=state, last_touched_at=self._clock())
            self._games[code] = game
            return game

    def get(self, code: str) -> Game | None:
        with self._lock:
            self._sweep_locked()
            game = self._games.get(code)
            if game is not None:
                game.last_touched_at = self._clock()
            return game

    def update(
        self,
        code: str,
        state: GameState,
        status: str | None = None,
        last_assignment: InningAssignment | None = None,
    ) -> Game | None:
        with self._lock:
            self._sweep_locked()
            game = self._games.get(code)
            if game is None:
                return None
            game.state = state
            if status is not None:
                game.status = status
            if last_assignment is not None:
                game.last_assignment = last_assignment
            game.last_touched_at = self._clock()
            return game

    def sweep(self) -> int:
        with self._lock:
            return self._sweep_locked()

    def _sweep_locked(self) -> int:
        now = self._clock()
        expired = [
            code
            for code, game in self._games.items()
            if now - game.last_touched_at > self._ttl
        ]
        for code in expired:
            del self._games[code]
        return len(expired)

    def __len__(self) -> int:
        return len(self._games)
