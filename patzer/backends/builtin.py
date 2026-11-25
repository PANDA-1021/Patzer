"""The built-in pure-Python engine."""
from __future__ import annotations

import chess

from patzer.engine.search import score_root_moves
from patzer.engine.strength import pick_move, strength_params


class BuiltinBackend:
    name = "Built-in engine"

    def __init__(self, elo: int):
        self.set_elo(elo)

    def set_elo(self, elo: int) -> None:
        self.elo = elo
        self.params = strength_params(elo)

    def choose_move(self, board: chess.Board) -> chess.Move:
        board = board.copy(stack=False)  # never touch the caller's board (runs in a worker thread)
        moves = list(board.legal_moves)
        if not moves:
            raise ValueError("no legal moves")
        if len(moves) == 1:
            return moves[0]
        scored = score_root_moves(board, self.params.depth)
        return pick_move(scored, self.params)

    def close(self) -> None:
        pass
