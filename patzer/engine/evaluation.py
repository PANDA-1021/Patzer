"""Static position evaluation."""
from __future__ import annotations

import chess

PIECE_VALUES = {
    chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
    chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 0,
}


def center_dist(sq: int) -> float:
    """Chebyshev distance from the board centre (0.5 in the middle .. 3.5 in a corner)."""
    return max(abs(chess.square_file(sq) - 3.5), abs(chess.square_rank(sq) - 3.5))


def _mop_up(attacker_king: int, defender_king: int) -> float:
    """Endgame bonus: drive the defending king to the edge, bring own king close."""
    return 10 * center_dist(defender_king) + 4 * (7 - chess.square_distance(attacker_king, defender_king))


def evaluate(board: chess.Board) -> float:
    """Static score in centipawns from the side-to-move's perspective."""
    score = 0.0
    piece_material = 0
    wk = bk = 0
    for sq, piece in board.piece_map().items():
        pt = piece.piece_type
        value = PIECE_VALUES[pt]
        centrality = 3.5 - center_dist(sq)  # 0 (edge) .. 3 (center)
        if pt in (chess.KNIGHT, chess.BISHOP):
            value += centrality * 8
        elif pt == chess.PAWN:
            rank = chess.square_rank(sq)
            progress = rank if piece.color == chess.WHITE else 7 - rank
            value += progress * 6 + centrality * 2
        elif pt == chess.KING:
            if piece.color == chess.WHITE:
                wk = sq
            else:
                bk = sq
        if pt not in (chess.PAWN, chess.KING):
            piece_material += PIECE_VALUES[pt]
        score += value if piece.color == chess.WHITE else -value

    if piece_material <= 1400:  # endgame: help the stronger side actually finish
        if score > 150:
            score += _mop_up(wk, bk)
        elif score < -150:
            score -= _mop_up(bk, wk)

    return score if board.turn == chess.WHITE else -score
