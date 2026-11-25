"""Pure-logic tests (no python-chess needed)."""
import random

from patzer.engine.strength import PIECE_BLUNDER_RATE, pick_move, strength_params
from patzer.tools.stats import elo_from_score, summarize


def test_depth_never_below_two():
    for elo in range(0, 3000, 50):
        assert strength_params(elo).depth >= 2


def test_stronger_elo_means_fewer_mistakes():
    weak, strong = strength_params(1000), strength_params(2000)
    assert weak.miss_prob > strong.miss_prob
    assert weak.blunder_prob > strong.blunder_prob
    assert weak.tie_window > strong.tie_window


def test_piece_blunder_rate_is_tiny_at_1000():
    assert strength_params(1000).blunder_prob <= PIECE_BLUNDER_RATE


def test_free_material_is_almost_always_taken():
    scored = [("capture", 300.0)] + [(f"quiet{i}", 0.0) for i in range(30)]
    rng = random.Random(1)
    params = strength_params(1000)
    hits = sum(pick_move(scored, params, rng) == "capture" for _ in range(5000))
    assert hits / 5000 > 0.97


def test_elo_math():
    assert abs(elo_from_score(0.5)) < 1e-9
    assert abs(elo_from_score(0.76) - 200) < 5


def test_summarize_flags_saturation():
    assert summarize([0.0] * 40, 1320)["saturated"]
    assert not summarize([1.0, 0.0] * 20, 1320)["saturated"]
