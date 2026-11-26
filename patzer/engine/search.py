"""Alpha-beta (negamax) search with quiescence."""
from __future__ import annotations

import math

import chess

from .evaluation import PIECE_VALUES, evaluate
from .strength import PIECE_LOSS_RANGE

MATE = 100_000
SCORE_CLAMP = 1500.0     # root scores are clamped so mate scores don't dominate
QUIESCENCE_DEPTH = 6     # max extra capture plies searched at the horizon
DELTA_MARGIN = 200       # quiescence skips captures that cannot lift the score within this margin
ROOT_WINDOW = PIECE_LOSS_RANGE[1] + 1   # root moves worse than best by more than this are never picked


def _move_key(board: chess.Board, move: chess.Move) -> int:
    """MVV-LVA style ordering: promotions and big captures by small pieces first."""
    key = 800 if move.promotion else 0
    if board.is_capture(move):
        victim = board.piece_type_at(move.to_square) or chess.PAWN  # en passant
        attacker = board.piece_type_at(move.from_square)
        key += 10 * PIECE_VALUES[victim] - PIECE_VALUES[attacker]
    return key


def order_moves(board: chess.Board) -> list[chess.Move]:
    return sorted(board.legal_moves, key=lambda m: _move_key(board, m), reverse=True)


def order_captures(board: chess.Board) -> list[chess.Move]:
    return sorted(board.generate_legal_captures(), key=lambda m: _move_key(board, m), reverse=True)


def quiescence(board: chess.Board, alpha: float, beta: float, ply: int,
               qdepth: int = QUIESCENCE_DEPTH) -> float:
    """Resolve pending captures so the static evaluation is never taken mid-exchange."""
    in_check = board.is_check()
    stand_pat = -math.inf
    if in_check:
        moves = order_moves(board)          # must answer the check: look at every evasion
        if not moves:
            return -MATE + ply
        if qdepth <= 0:
            return evaluate(board)
        best = -math.inf
    else:
        stand_pat = evaluate(board)
        if stand_pat >= beta or qdepth <= 0:
            return stand_pat
        best = stand_pat
        alpha = max(alpha, stand_pat)
        moves = order_captures(board)

    for move in moves:
        if not in_check:  # delta pruning: this capture cannot possibly raise the score enough
            victim = board.piece_type_at(move.to_square) or chess.PAWN
            if stand_pat + PIECE_VALUES[victim] + DELTA_MARGIN < alpha:
                continue
        board.push(move)
        score = -quiescence(board, -beta, -alpha, ply + 1, qdepth - 1)
        board.pop()
        if score > best:
            best = score
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
    return best


def negamax(board: chess.Board, depth: int, alpha: float, beta: float, ply: int) -> float:
    if depth <= 0:
        return quiescence(board, alpha, beta, ply)
    moves = order_moves(board)
    if not moves:
        return -MATE + ply if board.is_check() else 0
    if board.is_insufficient_material():
        return 0
    best = -math.inf
    for move in moves:
        board.push(move)
        score = -negamax(board, depth - 1, -beta, -alpha, ply + 1)
        board.pop()
        if score > best:
            best = score
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
    return best


def score_root_moves(board: chess.Board, depth: int) -> list[tuple[chess.Move, float]]:
    """Score every legal move from the mover's perspective.

    Scores are exact for every move within ROOT_WINDOW of the best one, which is all the
    move picker ever looks at. Clearly worse moves come back as an upper bound (still far
    below the best), which lets the search prune them quickly.
    """
    scored = []
    best = -math.inf
    for move in order_moves(board):
        floor = best - ROOT_WINDOW if best > -math.inf else -math.inf
        board.push(move)
        s = -negamax(board, depth - 1, -math.inf, -floor, 1)
        board.pop()
        s = max(-SCORE_CLAMP, min(SCORE_CLAMP, s))
        scored.append((move, s))
        best = max(best, s)
    return scored
