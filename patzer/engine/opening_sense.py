"""Opening principles for positions the repertoire doesn't cover.

When the opponent steps out of your theory the bot is on its own. Rather than leaving the first
moves entirely to a shallow search, this nudges the root move scores (in centipawns) toward:

  * development   - minor pieces off the back rank, not to the rim
  * the centre    - pawns on d4/e4/d5/e5, more of the four centre squares controlled
  * king safety   - castle; don't walk the king or give up castling rights; keep the queen home

Bonuses are small (a few tens of centipawns) so they only break ties between sensible moves:
winning material or avoiding a blunder always matters far more. They fade out between ply 24 and 36.
Set config.OPENING_SENSE = 0 to switch it off.
"""
from __future__ import annotations

from typing import Sequence

import chess

DEVELOP = 20.0
RIM_KNIGHT = -26.0
CASTLE = 40.0
KING_WALK = -55.0          # king moves (not castling) while castling is still available
ROOK_MOVE = -12.0          # rook moves that give up castling rights
EARLY_QUEEN = -20.0        # queen sortie with 2+ minor pieces still at home
RIM_PAWN = -10.0           # a/h pawn pushes in the first 10 moves
FLANK_ADVANCE = -10.0      # b/g pawn pushed past the 3rd rank while 2+ minors are undeveloped
CENTER_PAWN = 14.0         # pawn lands on d4/e4/d5/e5
CENTER_CONTROL = 5.0       # per extra centre square attacked or held
FULL_UNTIL, ZERO_AT = 24, 36   # plies

_CENTER = (chess.D4, chess.E4, chess.D5, chess.E5)
_HOME_MINORS = {
    chess.WHITE: (chess.B1, chess.G1, chess.C1, chess.F1),
    chess.BLACK: (chess.B8, chess.G8, chess.C8, chess.F8),
}


def phase_weight(ply: int) -> float:
    if ply <= FULL_UNTIL:
        return 1.0
    if ply >= ZERO_AT:
        return 0.0
    return (ZERO_AT - ply) / (ZERO_AT - FULL_UNTIL)


def _center_control(board: chess.Board, color: bool) -> int:
    n = 0
    for sq in _CENTER:
        piece = board.piece_at(sq)
        if (piece is not None and piece.color == color) or board.is_attacked_by(color, sq):
            n += 1
    return n


def move_bonus(board: chess.Board, move: chess.Move) -> float:
    """Centipawn nudge for `move` (positive = good by opening principles)."""
    mover = board.turn
    piece = board.piece_type_at(move.from_square)
    home_rank = 0 if mover == chess.WHITE else 7
    is_capture = board.is_capture(move)
    bonus = 0.0

    if piece in (chess.KNIGHT, chess.BISHOP) and chess.square_rank(move.from_square) == home_rank \
            and chess.square_rank(move.to_square) != home_rank:
        bonus += DEVELOP
        if piece == chess.KNIGHT and chess.square_file(move.to_square) in (0, 7):
            bonus += RIM_KNIGHT

    if board.is_castling(move):
        bonus += CASTLE
    elif not board.is_check():
        if piece == chess.KING and board.has_castling_rights(mover):
            bonus += KING_WALK
        elif piece == chess.ROOK and board.has_castling_rights(mover) \
                and move.from_square in (chess.A1, chess.H1, chess.A8, chess.H8):
            bonus += ROOK_MOVE

    if piece == chess.QUEEN and not is_capture:
        minors_home = sum(1 for sq in _HOME_MINORS[mover]
                          if (p := board.piece_at(sq)) and p.color == mover
                          and p.piece_type in (chess.KNIGHT, chess.BISHOP))
        if minors_home >= 2:
            bonus += EARLY_QUEEN

    if piece == chess.PAWN:
        steps = abs(chess.square_rank(move.to_square) - home_rank)
        if chess.square_file(move.from_square) in (1, 6) and steps >= 3 and not is_capture \
                and board.fullmove_number <= 10:
            bonus += FLANK_ADVANCE
        if chess.square_file(move.from_square) in (0, 7) and not is_capture and board.fullmove_number <= 10:
            bonus += RIM_PAWN
        if move.to_square in _CENTER and move.from_square not in _CENTER:
            bonus += CENTER_PAWN

    before = _center_control(board, mover)
    board.push(move)
    try:
        after = _center_control(board, mover)
    finally:
        board.pop()
    return bonus + CENTER_CONTROL * (after - before)


def adjust_scores(board: chess.Board, scored: Sequence[tuple[chess.Move, float]],
                  scale: float = 1.0) -> list[tuple[chess.Move, float]]:
    """Add the opening-principle nudges to root move scores (no-op once the opening is over)."""
    w = phase_weight(board.ply()) * scale
    if w <= 0:
        return list(scored)
    return [(m, s + w * move_bonus(board, m)) for m, s in scored]
