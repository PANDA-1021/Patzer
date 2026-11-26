"""Opening book tests. Requires python-chess."""
import random

import chess

from patzer.backends import make_backend
from patzer.engine.book import REPERTOIRE, build_book, book_move, position_key


def test_every_repertoire_line_is_legal():
    _, bad = build_book()
    assert bad == [], f"illegal or misspelled lines: {bad}"


def test_lines_are_not_too_long():
    assert all(len(line.split()) <= 14 for _, line in REPERTOIRE)


def test_book_has_a_first_move_for_white():
    move = book_move(chess.Board(), max_plies=10, forget_prob=0.0, rng=random.Random(1))
    assert move in chess.Board().legal_moves


def test_book_replies_as_black_after_e4():
    board = chess.Board()
    board.push_san("e4")
    move = book_move(board, max_plies=10, forget_prob=0.0, rng=random.Random(1))
    assert move is not None and move in board.legal_moves


def test_out_of_book_returns_none():
    board = chess.Board()
    for san in ("a3", "h6", "Nc3"):
        board.push_san(san)
    assert book_move(board, max_plies=10, forget_prob=0.0) is None


def test_book_depth_limit_is_respected():
    board = chess.Board()
    for san in ("e4", "e5", "Nf3", "Nc6"):
        board.push_san(san)
    assert book_move(board, max_plies=10, forget_prob=0.0) is not None
    assert book_move(board, max_plies=4, forget_prob=0.0) is None


def test_book_works_without_move_history():
    board = chess.Board()
    board.push_san("d4")
    fresh = chess.Board(board.fen())  # no move stack, as the backend sees it
    assert position_key(fresh) == position_key(board)
    assert book_move(fresh, max_plies=10, forget_prob=0.0) is not None


def test_forgetting_makes_it_think_for_itself():
    assert book_move(chess.Board(), max_plies=10, forget_prob=1.0) is None


def test_backend_plays_a_sensible_first_move():
    random.seed(0)
    # The bot "forgets" the book about 5% of the time on purpose, so require most - not all - replies to be sensible.
    sensible = {chess.Move.from_uci(m) for m in ("e2e4", "d2d4", "c2c4", "g1f3", "e2e3")}
    moves = [make_backend(1000).choose_move(chess.Board()) for _ in range(30)]
    assert sum(m in sensible for m in moves) >= 24
