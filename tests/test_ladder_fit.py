"""Rating-fit maths (pure Python, no chess needed)."""
import random

import pytest

from patzer.tools.stats import _expected, fit_ratings

TRUE = {"A": 1000.0, "B": 1200.0, "C": 1450.0, "SF": 1320.0}
PAIRS = [("A", "B"), ("B", "C"), ("A", "C"), ("B", "SF"), ("C", "SF")]


def test_recovers_known_ratings_from_exact_expected_scores():
    results = {(a, b): (1000 * _expected(TRUE[a], TRUE[b]), 1000) for a, b in PAIRS}
    fit = fit_ratings(results, {"SF": 1320.0})
    for name in ("A", "B", "C"):
        assert abs(fit[name][0] - TRUE[name]) < 3


def test_recovers_ratings_from_simulated_games():
    rng = random.Random(7)
    results = {}
    for a, b in PAIRS:
        p = _expected(TRUE[a], TRUE[b])
        pts = sum(1.0 if rng.random() < p else 0.0 for _ in range(400))
        results[(a, b)] = (pts, 400)
    fit = fit_ratings(results, {"SF": 1320.0})
    for name in ("A", "B", "C"):
        rating, se = fit[name]
        assert abs(rating - TRUE[name]) < 4 * se + 5   # within sampling error
        assert 0 < se < 40


def test_all_losses_stay_finite():
    fit = fit_ratings({("A", "SF"): (0.0, 40)}, {"SF": 1320.0})
    assert 400 < fit["A"][0] < 1320


def test_unlinked_player_is_rejected():
    with pytest.raises(ValueError):
        fit_ratings({("A", "B"): (5.0, 10), ("C", "SF"): (5.0, 10)}, {"SF": 1320.0})


def test_needs_an_anchor():
    with pytest.raises(ValueError):
        fit_ratings({("A", "B"): (5.0, 10)}, {})


def test_anchor_is_unchanged():
    fit = fit_ratings({("A", "SF"): (6.0, 10)}, {"SF": 1320.0})
    assert fit["SF"] == (1320.0, 0.0)
