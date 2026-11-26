"""A small opening repertoire, so the bot starts games like a club player.

Lines are written in SAN and weighted (higher = played more often). A move's
weight is the sum of the weights of every line it appears in, and positions are
matched by board position, so transpositions work. How deep the bot stays in
book, and how often it "forgets" a move, depend on its Elo (see strength.py).
"""
from __future__ import annotations

import json
import random
from functools import lru_cache
from pathlib import Path

import chess

HUMAN_BOOK_PATH = Path(__file__).resolve().parent.parent / "data" / "book_human.json"

# (weight, line). Keep lines to <= 14 plies. A test checks that every line is legal.
REPERTOIRE: list[tuple[int, str]] = [
    # --- 1.e4 e5 ---
    (3, "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d3 d6 O-O O-O"),                  # Italian
    (2, "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6"),   # Ruy Lopez
    (1, "e4 e5 Nf3 Nc6 d4 exd4 Nxd4 Bc5 Be3 Qf6 c3 Nge7 Bc4 O-O"),      # Scotch
    # --- 1.e4 other defences ---
    (2, "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6 Be2 e5 Nb3 Be7"),  # Sicilian
    (1, "e4 c5 Nf3 Nc6 d4 cxd4 Nxd4 g6 Nc3 Bg7 Be3 Nf6 Bc4 O-O"),        # Sicilian, Dragon-style
    (1, "e4 e6 d4 d5 Nc3 Nf6 Bg5 Be7 e5 Nfd7 Bxe7 Qxe7 f4 O-O"),         # French
    (1, "e4 c6 d4 d5 Nc3 dxe4 Nxe4 Bf5 Ng3 Bg6 h4 h6 Nf3 Nd7"),          # Caro-Kann
    (1, "e4 d5 exd5 Qxd5 Nc3 Qa5 d4 Nf6 Nf3 c6 Bc4 Bf5 Bd2 e6"),         # Scandinavian
    (1, "e4 d6 d4 Nf6 Nc3 g6 Nf3 Bg7 Be2 O-O O-O c6"),                    # Pirc
    # --- 1.d4 ---
    (2, "d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7 e3 O-O Nf3 h6 Bh4 b6"),             # Queen's Gambit Declined
    (1, "d4 d5 c4 dxc4 Nf3 Nf6 e3 e6 Bxc4 c5 O-O a6"),                    # Queen's Gambit Accepted
    (1, "d4 d5 c4 c6 Nf3 Nf6 Nc3 dxc4 a4 Bf5 e3 e6 Bxc4 Bb4"),            # Slav
    (2, "d4 d5 Bf4 Nf6 e3 c5 c3 Nc6 Nd2 e6 Ngf3 Bd6 Bg3 O-O"),           # London
    (1, "d4 Nf6 Bf4 d5 e3 e6 Nf3 c5 c3 Nc6 Nbd2 Bd6 Bg3 O-O"),            # London, 1...Nf6
    (1, "d4 Nf6 c4 e6 Nc3 Bb4 e3 O-O Bd3 d5 Nf3 c5 O-O Nc6"),             # Nimzo-Indian
    (1, "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6 Nf3 O-O Be2 e5 O-O Nc6"),             # King's Indian
    # --- flank openings ---
    (1, "c4 e5 Nc3 Nf6 Nf3 Nc6 g3 d5 cxd5 Nxd5 Bg2 Nb6 O-O Be7"),         # English
    (1, "Nf3 d5 g3 Nf6 Bg2 c6 O-O Bg4 d3 Nbd7 Nbd2 e6"),                  # Reti
]


def position_key(board: chess.Board) -> str:
    """Position identity that ignores the move counters."""
    return " ".join(board.fen().split()[:4])


def build_book() -> tuple[dict[str, dict[str, int]], list[str]]:
    """Return ({position: {uci move: weight}}, lines that failed to parse)."""
    book: dict[str, dict[str, int]] = {}
    bad: list[str] = []
    for weight, line in REPERTOIRE:
        board = chess.Board()
        steps: list[tuple[str, str]] = []
        try:
            for san in line.split():
                move = board.parse_san(san)
                steps.append((position_key(board), move.uci()))
                board.push(move)
        except ValueError:
            bad.append(line)
            continue
        for key, uci in steps:
            entry = book.setdefault(key, {})
            entry[uci] = entry.get(uci, 0) + weight
    return book, bad


def load_human_book(path: Path = HUMAN_BOOK_PATH) -> dict[str, dict[str, int]]:
    """Opening moves mined from real games by `fit_human.py book` ({} if not built)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


@lru_cache(maxsize=1)
def _book() -> dict[str, dict[str, int]]:
    book = build_book()[0]
    book.update(load_human_book())   # human statistics win wherever they cover a position
    return book


def book_move(board: chess.Board, max_plies: int, forget_prob: float,
              rng: random.Random | None = None) -> chess.Move | None:
    """A weighted book move, or None if out of book (or the bot 'forgot' it)."""
    rng = rng if rng is not None else random
    if board.ply() >= max_plies:
        return None
    entry = _book().get(position_key(board))
    if not entry or rng.random() < forget_prob:
        return None
    moves, weights = [], []
    for uci, w in entry.items():
        move = chess.Move.from_uci(uci)
        if move in board.legal_moves:
            moves.append(move)
            weights.append(w)
    if not moves:
        return None
    return rng.choices(moves, weights=weights, k=1)[0]
