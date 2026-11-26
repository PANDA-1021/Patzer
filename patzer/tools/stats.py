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


# ---------------------------------------------------------------------------
# Rating fit for a whole ladder of players (Bradley-Terry / Elo maximum likelihood)
# ---------------------------------------------------------------------------
_K = math.log(10) / 400


def _expected(ra: float, rb: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400))


def _invert(m: list[list[float]]) -> list[list[float]]:
    """Gauss-Jordan inverse with partial pivoting (matrices here are tiny)."""
    n = len(m)
    a = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(m)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-12:
            raise ValueError("singular matrix: some player is not linked to an anchor")
        a[col], a[piv] = a[piv], a[col]
        d = a[col][col]
        a[col] = [x / d for x in a[col]]
        for r in range(n):
            if r != col and a[r][col]:
                f = a[r][col]
                a[r] = [x - f * y for x, y in zip(a[r], a[col])]
    return [row[n:] for row in a]


def fit_ratings(results: dict[tuple[str, str], tuple[float, int]],
                anchors: dict[str, float],
                iterations: int = 100) -> dict[str, tuple[float, float]]:
    """Fit Elo ratings to head-to-head results.

    results  {(a, b): (points scored by a, games played)}  (draws count 0.5)
    anchors  {player: rating} held fixed; at least one is required
    returns  {player: (rating, standard error)}  (anchors get standard error 0)

    Each pairing gets one virtual draw so all-win / all-loss results stay finite.
    """
    if not anchors:
        raise ValueError("at least one anchor rating is required")
    names = sorted({n for pair in results for n in pair} | set(anchors))

    # Every player must be connected to an anchor through some chain of games.
    linked, frontier = set(anchors), set(anchors)
    while frontier:
        nxt = set()
        for a, b in results:
            for x, y in ((a, b), (b, a)):
                if x in frontier and y not in linked:
                    nxt.add(y)
        linked |= nxt
        frontier = nxt
    unlinked = [n for n in names if n not in linked]
    if unlinked:
        raise ValueError(f"not linked to an anchor by any games: {unlinked}")

    data = {pair: (pts + 0.5, n + 1) for pair, (pts, n) in results.items()}
    free = [n for n in names if n not in anchors]
    idx = {n: i for i, n in enumerate(free)}
    start = sum(anchors.values()) / len(anchors)
    rating = {n: anchors.get(n, start) for n in names}
    cov: list[list[float]] = []

    for _ in range(iterations):
        g = [0.0] * len(free)
        h = [[0.0] * len(free) for _ in free]          # negative Hessian of the log-likelihood
        for (a, b), (pts, n) in data.items():
            p = _expected(rating[a], rating[b])
            w = _K * _K * n * p * (1 - p)
            grad = _K * (pts - n * p)
            if a in idx:
                g[idx[a]] += grad
                h[idx[a]][idx[a]] += w
            if b in idx:
                g[idx[b]] -= grad
                h[idx[b]][idx[b]] += w
            if a in idx and b in idx:
                h[idx[a]][idx[b]] -= w
                h[idx[b]][idx[a]] -= w
        if not free:
            break
        cov = _invert(h)
        step = [sum(cov[i][j] * g[j] for j in range(len(free))) for i in range(len(free))]
        step = [max(-150.0, min(150.0, s)) for s in step]
        for n, s in zip(free, step):
            rating[n] += s
        if max(abs(s) for s in step) < 1e-7:
            break

    out = {n: (rating[n], 0.0) for n in anchors}
    for n in free:
        out[n] = (rating[n], math.sqrt(cov[idx[n]][idx[n]]))
    return out
