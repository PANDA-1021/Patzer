"""Maps a target Elo to bot behaviour, and picks moves imperfectly on purpose.

This module is pure logic (no chess dependency), so it is easy to test.
"""
from __future__ import annotations

import math
import random
from typing import Any, NamedTuple

# Chance (at 400 Elo, shrinking to 0 at 2200) that a bot move gives up a piece
# in one move. Kept very low on purpose: at 1000 Elo it is about 0.3% per move.
PIECE_BLUNDER_RATE = 0.005
PIECE_LOSS_RANGE = (250, 700)   # a piece-losing blunder costs 250-700 centipawns


class StrengthParams(NamedTuple):
    """
    depth         plies the bot looks ahead (always >= 2, so it sees any reply that
                  captures a piece it just left hanging)
    blunder_prob  rare chance of a one-move blunder that gives up a piece
    miss_prob     chance of a soft mistake: a small inaccuracy that costs at most
                  about a pawn (passing up a pawn win, leaving a pawn loose, ...)
    tie_window    normal moves are picked among moves within this many centipawns
                  of the best one, so real material gains are always taken
    miss_window   soft mistakes are picked within this many centipawns of the best
    book_plies    stay in the opening book for this many plies (half-moves)
    book_forget   chance per move of 'forgetting' the book and thinking for itself

    Missed tactics (forks, pins, traps) come from the limited search depth.
    """
    depth: int
    blunder_prob: float
    miss_prob: float
    tie_window: float
    miss_window: float
    book_plies: int = 10
    book_forget: float = 0.05


def strength_params(elo: int) -> StrengthParams:
    elo = max(400, min(2200, elo))
    if elo < 1400:
        depth = 2
    elif elo < 1900:
        depth = 3
    else:
        depth = 4
    t = (elo - 400) / 1800  # 0..1
    return StrengthParams(
        depth=depth,
        blunder_prob=PIECE_BLUNDER_RATE * (1 - t) ** 1.2,
        miss_prob=0.25 * (1 - t) ** 1.2,
        tie_window=15 + 45 * (1 - t),
        miss_window=100 + 100 * (1 - t),
        book_plies=6 + elo // 250,          # 1000 Elo: 10 plies, 2200 Elo: 14
        book_forget=0.01 + 0.07 * (1 - t),  # 1000 Elo: about 5% per move
    )


def pick_move(scored: list[tuple[Any, float]], params: StrengthParams,
              rng: Any = None, prefer_scale: float | None = None) -> Any:
    """Choose a move from [(move, score), ...] according to the strength params.

    prefer_scale: if given, moves inside the chosen pool are picked with probability
    proportional to exp(-(deficit)/prefer_scale) instead of uniformly, so sounder moves are
    favoured (used in the opening, where many moves score almost the same).
    """
    rng = rng if rng is not None else random
    best = max(s for _, s in scored)
    roll = rng.random()
    if roll < params.blunder_prob:  # rare: gives up a piece
        lo, hi = PIECE_LOSS_RANGE
        pool = [m for m, s in scored if best - hi <= s <= best - lo]
        if pool:
            return rng.choice(pool)
    if roll < params.blunder_prob + params.miss_prob:  # small inaccuracy
        pool = [(m, s) for m, s in scored if s >= best - params.miss_window]
    else:  # best move, or a near-equal alternative
        pool = [(m, s) for m, s in scored if s >= best - params.tie_window]
    if prefer_scale:
        return rng.choices([m for m, _ in pool],
                           weights=[math.exp((s - best) / prefer_scale) for _, s in pool], k=1)[0]
    return rng.choice([m for m, _ in pool])
