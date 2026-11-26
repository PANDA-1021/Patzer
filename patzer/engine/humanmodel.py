"""A move-choice model learned from real human games.

The search (search.py) says how good every legal move is. This module says how likely a
*human of a given rating* is to play each of them, given that score gap plus a few cheap
features of the move (capture? check? lands on an attacked square? ...). It is a
conditional-logit ("softmax over candidate moves") model:

    P(move) = exp(w . features(move)) / sum over legal moves of exp(w . features)

Weights are fitted offline by `python -m patzer.tools.fit_human train ...` from PGN files
of human games, one weight vector per rating band. At play time the weights for the
target Elo are interpolated between the two nearest bands. Blunders then happen at the
rate and in the situations where real players at that level make them, instead of from a
fixed hand-tuned probability.

Runtime needs only the standard library and python-chess; training needs numpy + scipy.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Sequence

import chess

MODEL_PATH = Path(__file__).resolve().parent.parent / "data" / "human_model.json"

GAP_CAP = 8.0   # pawns; a gap bigger than this is treated as 8
FEATURE_NAMES = [
    "gap",                      # score deficit vs. the best move, in pawns (0..GAP_CAP)
    "gap_0.1_0.3", "gap_0.3_1", "gap_1_3", "gap_3_plus",   # non-linear shape of the gap
    "capture", "check", "promotion", "castle",
    "knight", "bishop", "rook", "queen", "king_walk",      # piece moved (pawn = baseline)
    "develops",                 # minor piece leaves its back rank
    "center_dest",              # lands on d4/e4/d5/e5
    "recapture",                # takes back on the square the opponent just captured on
    "lands_hanging",            # destination attacked by the opponent and undefended
    "lands_defended_attacked",  # destination attacked by the opponent but defended
    "escapes_attack",           # moves a non-king piece that was under attack
]
N_FEATURES = len(FEATURE_NAMES)
_PIECE_SLOT = {chess.KNIGHT: 9, chess.BISHOP: 10, chess.ROOK: 11, chess.QUEEN: 12}
_CENTER = (chess.D4, chess.E4, chess.D5, chess.E5)


def move_features(board: chess.Board, move: chess.Move, gap_cp: float,
                  last_move: chess.Move | None = None) -> list[float]:
    """Feature vector for one candidate move. `board` is restored before returning."""
    f = [0.0] * N_FEATURES
    gap = min(max(gap_cp, 0.0) / 100.0, GAP_CAP)
    f[0] = gap
    f[1] = 1.0 if 0.1 <= gap < 0.3 else 0.0
    f[2] = 1.0 if 0.3 <= gap < 1.0 else 0.0
    f[3] = 1.0 if 1.0 <= gap < 3.0 else 0.0
    f[4] = 1.0 if gap >= 3.0 else 0.0

    mover = board.turn
    piece = board.piece_type_at(move.from_square)
    is_capture = board.is_capture(move)
    f[5] = 1.0 if is_capture else 0.0
    f[6] = 1.0 if board.gives_check(move) else 0.0
    f[7] = 1.0 if move.promotion else 0.0
    f[8] = 1.0 if board.is_castling(move) else 0.0
    if piece in _PIECE_SLOT:
        f[_PIECE_SLOT[piece]] = 1.0
    if piece == chess.KING and not f[8]:
        f[13] = 1.0
    home_rank = 0 if mover == chess.WHITE else 7
    if piece in (chess.KNIGHT, chess.BISHOP) and chess.square_rank(move.from_square) == home_rank:
        f[14] = 1.0
    f[15] = 1.0 if move.to_square in _CENTER else 0.0
    if is_capture and last_move is not None and move.to_square == last_move.to_square:
        f[16] = 1.0
    if piece is not None and piece != chess.KING and board.is_attacked_by(not mover, move.from_square):
        f[19] = 1.0   # escapes_attack

    board.push(move)
    try:
        if board.is_attacked_by(not mover, move.to_square):
            if board.is_attacked_by(mover, move.to_square):
                f[18] = 1.0
            else:
                f[17] = 1.0
    finally:
        board.pop()
    return f


@dataclass
class HumanModel:
    bands: dict[int, list[float]]       # band centre Elo -> weights
    meta: dict

    def weights_for(self, elo: float) -> list[float]:
        """Weights for `elo`, interpolated linearly between the two nearest bands."""
        centres = sorted(self.bands)
        if elo <= centres[0]:
            return self.bands[centres[0]]
        if elo >= centres[-1]:
            return self.bands[centres[-1]]
        for lo, hi in zip(centres, centres[1:]):
            if lo <= elo <= hi:
                t = (elo - lo) / (hi - lo)
                return [a + t * (b - a) for a, b in zip(self.bands[lo], self.bands[hi])]
        raise AssertionError("unreachable")

    def probabilities(self, board: chess.Board, scored: Sequence[tuple[chess.Move, float]],
                      elo: float, temperature: float = 1.0,
                      last_move: chess.Move | None = None) -> list[float]:
        w = self.weights_for(elo)
        best = max(s for _, s in scored)
        logits = []
        for move, s in scored:
            f = move_features(board, move, best - s, last_move)
            logits.append(sum(a * b for a, b in zip(w, f)) / max(temperature, 1e-6))
        top = max(logits)
        exps = [math.exp(x - top) for x in logits]
        total = sum(exps)
        return [e / total for e in exps]

    def choose(self, board: chess.Board, scored: Sequence[tuple[chess.Move, float]], elo: float,
               rng: random.Random | None = None, temperature: float = 1.0,
               last_move: chess.Move | None = None) -> chess.Move:
        rng = rng if rng is not None else random
        probs = self.probabilities(board, scored, elo, temperature, last_move)
        return rng.choices([m for m, _ in scored], weights=probs, k=1)[0]


def save_model(path: Path, bands: dict[int, list[float]], meta: dict) -> None:
    payload = {"version": 1, "features": FEATURE_NAMES, "meta": meta,
               "bands": {str(k): v for k, v in sorted(bands.items())}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    load_model.cache_clear()


@lru_cache(maxsize=1)
def load_model(path: str | None = None) -> HumanModel | None:
    """The fitted model, or None if none has been trained (the app then uses strength.py)."""
    p = Path(path) if path else MODEL_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("features") != FEATURE_NAMES or not data.get("bands"):
        return None   # trained with a different feature set: ignore rather than misread
    return HumanModel({int(k): v for k, v in data["bands"].items()}, data.get("meta", {}))
