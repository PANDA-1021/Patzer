"""The fast table-driven evaluate() must match a plain, obviously-correct version."""
import random

import chess

from patzer.engine.evaluation import (CASTLED_BONUS, CENTER_PAWN_BONUS, EARLY_QUEEN_PENALTY,
                                      PIECE_VALUES, UNDEVELOPED_PENALTY, _CASTLED_KING,
                                      _HOME_MINORS, _QUEEN_HOME, _mop_up, center_dist, evaluate)


def reference_evaluate(board: chess.Board) -> float:
    """Straightforward piece-by-piece version (slow). Kept only to check the fast one."""
    score = 0.0
    piece_material = 0
    wk = bk = 0
    undeveloped = {chess.WHITE: 0, chess.BLACK: 0}
    queen_out = {chess.WHITE: False, chess.BLACK: False}
    for sq, piece in board.piece_map().items():
        pt = piece.piece_type
        value = PIECE_VALUES[pt]
        centrality = 3.5 - center_dist(sq)
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
    if piece_material > 1400:
        for color, sign in ((chess.WHITE, 1), (chess.BLACK, -1)):
            king_sq = wk if color == chess.WHITE else bk
            if king_sq in _CASTLED_KING[color]:
                score += sign * CASTLED_BONUS
            if queen_out[color] and undeveloped[color] >= 2:
                score -= sign * EARLY_QUEEN_PENALTY
    if piece_material <= 1400:
        if score > 150:
            score += _mop_up(wk, bk)
        elif score < -150:
            score -= _mop_up(bk, wk)
    return score if board.turn == chess.WHITE else -score


def test_fast_evaluate_matches_reference_on_random_games():
    rng = random.Random(42)
    checked = 0
    for _ in range(40):
        board = chess.Board()
        for _ in range(rng.randint(0, 120)):
            moves = list(board.legal_moves)
            if not moves:
                break
            board.push(rng.choice(moves))
            assert evaluate(board) == reference_evaluate(board), board.fen()
            checked += 1
    assert checked > 1000


def test_start_position_is_balanced():
    assert evaluate(chess.Board()) == 0
