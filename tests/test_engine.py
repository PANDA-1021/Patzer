"""Engine behaviour tests on concrete positions. Requires python-chess."""
import random

import chess
import pytest

from patzer.backends import make_backend
from patzer.engine.search import negamax, quiescence, score_root_moves, MATE


@pytest.fixture(autouse=True)
def _seed():
    random.seed(0)


def best_move(fen, elo=1000, tries=30):
    """Most common reply over several tries (the bot is random on purpose)."""
    bot = make_backend(elo)
    board = chess.Board(fen)
    counts = {}
    for _ in range(tries):
        m = bot.choose_move(board)
        counts[m] = counts.get(m, 0) + 1
    return max(counts, key=counts.get), counts


def test_does_not_modify_callers_board():
    board = chess.Board()
    before = board.fen()
    make_backend(1000).choose_move(board)
    assert board.fen() == before and not board.move_stack


def test_plays_mate_in_one():
    # White: Qh5-f7# (scholar's mate pattern)
    fen = "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
    _, counts = best_move(fen, tries=40)
    mate = chess.Move.from_uci("h5f7")
    assert counts.get(mate, 0) / 40 > 0.9


def test_takes_free_knight():
    # Black knight on d5 is undefended and attacked by the white pawn on e4.
    fen = "rnbqkb1r/pppppppp/8/3n4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 1"
    _, counts = best_move(fen, tries=60)
    assert counts.get(chess.Move.from_uci("e4d5"), 0) / 60 > 0.9


def test_does_not_hang_queen():
    # Qd1 is attacked by nothing now; moving it to a square covered by a pawn would hang it.
    board = chess.Board("rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2")
    bot = make_backend(1000)
    for _ in range(40):
        m = bot.choose_move(board)
        board.push(m)
        queen_hanging = any(
            board.is_attacked_by(chess.BLACK, sq) and not board.is_attacked_by(chess.WHITE, sq)
            for sq in board.pieces(chess.QUEEN, chess.WHITE)
        )
        board.pop()
        assert not queen_hanging


def test_handles_promotion():
    fen = "8/P7/8/8/8/8/7k/K7 w - - 0 1"
    move, _ = best_move(fen, tries=15)
    assert move.promotion == chess.QUEEN


def test_castling_and_en_passant_are_legal_choices():
    bot = make_backend(1000)
    for fen in ("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
                "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1"):
        board = chess.Board(fen)
        for _ in range(20):
            assert bot.choose_move(board) in board.legal_moves


def test_single_legal_move_is_returned():
    board = chess.Board("k7/2K5/8/8/8/8/8/1R6 b - - 0 1")  # only Ka7 is legal
    assert list(board.legal_moves) == [chess.Move.from_uci("a8a7")]
    assert make_backend(1000).choose_move(board) == chess.Move.from_uci("a8a7")


def test_quiescence_resolves_pending_recapture():
    # White's queen just took a pawn that is defended: Black to move can win the queen.
    board = chess.Board("4k3/8/2p5/3Q4/8/8/8/4K3 b - - 0 1")
    static = quiescence(board, -MATE, MATE, 0, qdepth=0)  # no look-ahead: stops mid-exchange
    resolved = quiescence(board, -MATE, MATE, 0)
    assert resolved > static + 500


def test_mate_score_is_found_at_depth_two():
    board = chess.Board("6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1")
    scored = dict(score_root_moves(board, 2))
    assert scored[chess.Move.from_uci("a1a8")] >= 1000
