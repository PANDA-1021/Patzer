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


def _build_tables() -> dict[tuple[bool, int], list[float]]:
    """Per-square value of each (colour, piece type), signed (+ for White, - for Black).

    Everything that depends only on *where* a piece stands is folded in here once,
    so evaluate() is just table lookups.
    """
    tables: dict[tuple[bool, int], list[float]] = {}
    for color in (chess.WHITE, chess.BLACK):
        for pt in chess.PIECE_TYPES:
            row = []
            for sq in chess.SQUARES:
                value = float(PIECE_VALUES[pt])
                centrality = 3.5 - center_dist(sq)  # 0 (edge) .. 3 (center)
                if pt in (chess.KNIGHT, chess.BISHOP):
                    value += centrality * 10
                    if sq in _HOME_MINORS[color]:
                        value -= UNDEVELOPED_PENALTY
                elif pt == chess.PAWN:
                    rank = chess.square_rank(sq)
                    progress = rank if color == chess.WHITE else 7 - rank
                    value += progress * 6 + centrality * 2
                    if sq in (chess.D4, chess.E4, chess.D5, chess.E5):
                        value += CENTER_PAWN_BONUS
                row.append(value if color == chess.WHITE else -value)
            tables[(color, pt)] = row
    return tables


_TABLES = _build_tables()
_HOME_MASK = {c: sum(1 << sq for sq in _HOME_MINORS[c]) for c in (chess.WHITE, chess.BLACK)}
_NOT_QUEEN_HOME = {c: ~(1 << _QUEEN_HOME[c]) for c in (chess.WHITE, chess.BLACK)}
_HEAVY_TYPES = (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)


def evaluate(board: chess.Board) -> float:
    """Static score in centipawns from the side-to-move's perspective."""
    score = 0.0
    piece_material = 0
    for color in (chess.WHITE, chess.BLACK):
        for pt in chess.PIECE_TYPES:
            mask = board.pieces_mask(pt, color)
            if not mask:
                continue
            row = _TABLES[(color, pt)]
            for sq in chess.scan_forward(mask):
                score += row[sq]
            if pt in _HEAVY_TYPES:
                piece_material += PIECE_VALUES[pt] * mask.bit_count()

    if piece_material > 1400:  # opening / middlegame: develop, castle, keep the queen home early
        for color, sign in ((chess.WHITE, 1), (chess.BLACK, -1)):
            king_sq = board.king(color)
            if king_sq in _CASTLED_KING[color]:
                score += sign * CASTLED_BONUS
            if board.pieces_mask(chess.QUEEN, color) & _NOT_QUEEN_HOME[color]:
                minors = board.pieces_mask(chess.KNIGHT, color) | board.pieces_mask(chess.BISHOP, color)
                if (minors & _HOME_MASK[color]).bit_count() >= 2:
                    score -= sign * EARLY_QUEEN_PENALTY
    else:  # endgame: help the stronger side actually finish
        wk, bk = board.king(chess.WHITE), board.king(chess.BLACK)
        if score > 150:
            score += _mop_up(wk, bk)
        elif score < -150:
            score -= _mop_up(bk, wk)

    return score if board.turn == chess.WHITE else -score
