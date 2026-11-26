"""Stockfish as a strength-limited opponent, using its UCI_Elo option."""
from __future__ import annotations

import threading

import chess
import chess.engine

from patzer.config import STOCKFISH_MAX_ELO, STOCKFISH_MIN_ELO, STOCKFISH_MOVETIME


class StockfishNotFound(RuntimeError):
    """Raised when a Stockfish strength was requested but no executable is known."""


def _default_factory(path: str):
    return chess.engine.SimpleEngine.popen_uci(path)


class StockfishBackend:
    name = "Stockfish"

    def __init__(self, elo: int, path: str, movetime: float = STOCKFISH_MOVETIME,
                 engine_factory=None):
        self.path = path
        self.movetime = movetime
        self._factory = engine_factory or _default_factory
        self._lock = threading.RLock()
        self._engine = None
        self.elo = self._clamp(elo)
        self.start()  # fail early (bad path, wrong file) instead of on the first move

    @staticmethod
    def _clamp(elo: int) -> int:
        return max(STOCKFISH_MIN_ELO, min(STOCKFISH_MAX_ELO, int(elo)))

    def start(self) -> None:
        with self._lock:
            if self._engine is not None:
                return
            engine = self._factory(self.path)
            try:
                engine.configure({"Threads": 1, "Hash": 64,
                                  "UCI_LimitStrength": True, "UCI_Elo": self.elo})
            except Exception:
                try:
                    engine.quit()
                except Exception:
                    pass
                raise
            self._engine = engine

    def set_elo(self, elo: int) -> None:
        with self._lock:
            self.elo = self._clamp(elo)
            if self._engine is not None:
                self._engine.configure({"UCI_Elo": self.elo})

    def choose_move(self, board: chess.Board) -> chess.Move:
        board = board.copy(stack=False)
        if not any(board.legal_moves):
            raise ValueError("no legal moves")
        limit = chess.engine.Limit(time=self.movetime)
        with self._lock:
            for attempt in (1, 2):
                try:
                    self.start()
                    result = self._engine.play(board, limit)
                    break
                except chess.engine.EngineError:   # includes the engine process dying
                    self._drop_engine()
                    if attempt == 2:
                        raise
        move = result.move
        if move is None or move not in board.legal_moves:
            raise RuntimeError(f"Stockfish returned an unusable move: {move}")
        return move

    def _drop_engine(self) -> None:
        engine, self._engine = self._engine, None
        if engine is not None:
            try:
                engine.quit()
            except Exception:
                pass

    def close(self) -> None:
        with self._lock:
            self._drop_engine()
