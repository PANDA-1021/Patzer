"""Static position evaluation."""
from __future__ import annotations

import chess

PIECE_VALUES = {
    chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
    chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 0,
}


# Squares where each side's minor pieces start, and the squares that count as "castled".
_HOME_MINORS = {
    chess.WHITE: {chess.B1, chess.G1, chess.C1, chess.F1},
    chess.BLACK: {chess.B8, chess.G8, chess.C8, chess.F8},
}
_CASTLED_KING = {
    chess.WHITE: {chess.B1, chess.C1, chess.G1, chess.H1},
    chess.BLACK: {chess.B8, chess.C8, chess.G8, chess.H8},
}
_QUEEN_HOME = {chess.WHITE: chess.D1, chess.BLACK: chess.D8}

UNDEVELOPED_PENALTY = 14   # per minor piece still on its starting square
CASTLED_BONUS = 28         # king tucked away (middlegame only)
EARLY_QUEEN_PENALTY = 18   # queen out while 2+ minor pieces are still at home
CENTER_PAWN_BONUS = 14     # pawn on d4/e4/d5/e5


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
    undeveloped = {chess.WHITE: 0, chess.BLACK: 0}
    queen_out = {chess.WHITE: False, chess.BLACK: False}
    for sq, piece in board.piece_map().items():
        pt = piece.piece_type
        value = PIECE_VALUES[pt]
        centrality = 3.5 - center_dist(sq)  # 0 (edge) .. 3 (center)
        if pt in (chess.KNIGHT, chess.BISHOP):
            value += centrality * 10
            if sq in _HOME_MINORS[piece.color]:
                value -= UNDEVELOPED_PENALTY
                undeveloped[piece.color] += 1
        elif pt == chess.QUEEN:
            if sq != _QUEEN_HOME[piece.color]:
                queen_out[piece.color] = True
        elif pt == chess.PAWN:
            rank = chess.square_rank(sq)
            progress = rank if piece.color == chess.WHITE else 7 - rank
            value += progress * 6 + centrality * 2
            if sq in (chess.D4, chess.E4, chess.D5, chess.E5):
                value += CENTER_PAWN_BONUS
        elif pt == chess.KING:
            if piece.color == chess.WHITE:
                wk = sq
            else:
                bk = sq
        if pt not in (chess.PAWN, chess.KING):
            piece_material += PIECE_VALUES[pt]
        score += value if piece.color == chess.WHITE else -value

    if piece_material > 1400:  # opening / middlegame: develop, castle, keep the queen home early
        for color, sign in ((chess.WHITE, 1), (chess.BLACK, -1)):
            king_sq = wk if color == chess.WHITE else bk
            if king_sq in _CASTLED_KING[color]:
                score += sign * CASTLED_BONUS
            if queen_out[color] and undeveloped[color] >= 2:
                score -= sign * EARLY_QUEEN_PENALTY

    if piece_material <= 1400:  # endgame: help the stronger side actually finish
        if score > 150:
            score += _mop_up(wk, bk)
        elif score < -150:
            score -= _mop_up(bk, wk)

    return score if board.turn == chess.WHITE else -score
