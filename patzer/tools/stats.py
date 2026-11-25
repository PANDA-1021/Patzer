"""Match statistics: turn game scores into Elo estimates (no chess dependency)."""
from __future__ import annotations

import math


def elo_from_score(p: float) -> float:
    """Elo difference implied by an expected score p in (0, 1)."""
    return -400.0 * math.log10(1.0 / p - 1.0)


def summarize(scores: list[float], opp_rating: float) -> dict:
    """Elo estimate and 95% CI from per-game scores (1, 0.5 or 0, bot's view).

    One virtual draw is added so 0% / 100% results stay finite.
    """
    n = len(scores)
    wins = sum(1 for s in scores if s == 1.0)
    draws = sum(1 for s in scores if s == 0.5)
    losses = n - wins - draws
    padded = scores + [0.5]
    m = sum(padded) / len(padded)
    var = sum((s - m) ** 2 for s in padded) / (len(padded) - 1)
    se = math.sqrt(var / len(padded))
    lo, hi = max(0.01, m - 1.96 * se), min(0.99, m + 1.96 * se)
    m = min(0.99, max(0.01, m))
    return {
        "games": n, "wins": wins, "draws": draws, "losses": losses,
        "score": sum(scores) / n if n else 0.0,
        "elo": opp_rating + elo_from_score(m),
        "elo_low": opp_rating + elo_from_score(lo),
        "elo_high": opp_rating + elo_from_score(hi),
        "saturated": m < 0.1 or m > 0.9,
    }
