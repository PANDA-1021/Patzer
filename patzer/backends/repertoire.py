"""Makes any backend (Stockfish) follow the opening repertoire first."""
from __future__ import annotations

import chess

from patzer import config
from patzer.engine.repertoire import repertoire_move


class RepertoireBackend:
    def __init__(self, inner):
        self.inner = inner
        self.name = f"{inner.name} + opening repertoire"

    @property
    def elo(self) -> int:
        return self.inner.elo

    def set_elo(self, elo: int) -> None:
        self.inner.set_elo(elo)

    def choose_move(self, board: chess.Board) -> chess.Move:
        move = repertoire_move(board.copy(stack=False), config.REPERTOIRE_MAX_PLIES, config.REPERTOIRE_FORGET)
        return move if move is not None else self.inner.choose_move(board)

    def close(self) -> None:
        self.inner.close()
