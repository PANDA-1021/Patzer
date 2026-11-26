"""The built-in pure-Python engine."""
from __future__ import annotations

import chess

from patzer import config
from patzer.engine.book import book_move
from patzer.engine.humanmodel import load_model
from patzer.engine.opening_sense import adjust_scores, phase_weight
from patzer.engine.repertoire import repertoire_move
from patzer.engine.search import score_root_moves
from patzer.engine.strength import pick_move, strength_params


class BuiltinBackend:
    name = "Built-in engine"

    def __init__(self, elo: int, use_book: bool = True, use_model: bool | None = None):
        self.use_book = use_book
        self.use_model = config.HUMAN_MODEL_ENABLED if use_model is None else use_model
        self.set_elo(elo)

    def set_elo(self, elo: int) -> None:
        self.elo = elo
        self.params = strength_params(elo)

    def choose_move(self, board: chess.Board) -> chess.Move:
        last_move = board.peek() if board.move_stack else None
        board = board.copy(stack=False)  # never touch the caller's board (runs in a worker thread)
        moves = list(board.legal_moves)
        if not moves:
            raise ValueError("no legal moves")
        if len(moves) == 1:
            return moves[0]
        if self.use_book:
            if config.REPERTOIRE_MODE:
                move = repertoire_move(board, config.REPERTOIRE_MAX_PLIES, config.REPERTOIRE_FORGET)
            else:
                move = book_move(board, self.params.book_plies, self.params.book_forget)
            if move is not None:
                return move
        scored = score_root_moves(board, self.params.depth)
        if config.OPENING_SENSE > 0:
            scored = adjust_scores(board, scored, config.OPENING_SENSE)
        model = load_model() if self.use_model else None
        if model is not None:
            return model.choose(board, scored, self.elo, temperature=config.HUMAN_MODEL_TEMPERATURE,
                                last_move=last_move)
        prefer = config.OPENING_PREFER_SCALE if config.OPENING_SENSE > 0 and phase_weight(board.ply()) > 0 else None
        return pick_move(scored, self.params, prefer_scale=prefer)

    def close(self) -> None:
        pass
