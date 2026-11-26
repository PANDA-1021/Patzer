"""Human-model features, fitting, book mining and error profiling."""
import io
import json
import random

import chess
import chess.pgn
import pytest

from patzer.engine import humanmodel
from patzer.engine.humanmodel import FEATURE_NAMES, HumanModel, load_model, move_features
from patzer.tools import fit_human
from patzer.backends import make_backend


def feat(fen, uci, gap=0.0, last=None):
    board = chess.Board(fen)
    f = move_features(board, chess.Move.from_uci(uci), gap, last)
    assert board.fen() == fen          # board must be restored
    return dict(zip(FEATURE_NAMES, f))


def test_features_flag_captures_checks_and_hanging_pieces():
    # Qxf7# style position: capture + check
    f = feat("r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4", "h5f7")
    assert f["capture"] == 1 and f["check"] == 1 and f["queen"] == 1
    # After 1.e4 d5 the c8-bishop covers g4, so Qg4 walks into an attack with no defender
    f = feat("rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2", "d1g4")
    assert f["queen"] == 1 and f["lands_hanging"] == 1
    # After 1.e4 e5 nothing covers h5
    f = feat("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2", "d1h5")
    assert f["lands_hanging"] == 0
    # After 1.e4 e5 2.Nf3 Nf6 the knight attacks h5
    f = feat("rnbqkb1r/pppp1ppp/5n2/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3", "d1h5")
    assert f["lands_hanging"] == 1


def test_gap_bins():
    assert feat(chess.STARTING_FEN, "e2e4", gap=0)["gap_3_plus"] == 0
    assert feat(chess.STARTING_FEN, "e2e4", gap=450)["gap_3_plus"] == 1
    assert feat(chess.STARTING_FEN, "e2e4", gap=450)["gap"] == pytest.approx(4.5)
    assert feat(chess.STARTING_FEN, "e2e4", gap=5000)["gap"] == humanmodel.GAP_CAP


def test_band_interpolation_and_clamping():
    m = HumanModel({1000: [0.0] * 20, 1200: [2.0] * 20}, {})
    assert m.weights_for(900) == [0.0] * 20
    assert m.weights_for(1300) == [2.0] * 20
    assert m.weights_for(1100) == pytest.approx([1.0] * 20)


def test_probabilities_prefer_better_moves_and_take_free_material():
    w = [0.0] * 20
    w[0] = -1.5     # gap
    w[5] = 0.3      # capture
    model = HumanModel({1000: w}, {})
    board = chess.Board("rnbqkb1r/pppppppp/8/3n4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 1")
    scored = [(m, 0.0) for m in board.legal_moves]
    take = chess.Move.from_uci("e4d5")
    scored = [(m, 300.0 if m == take else 0.0) for m, _ in scored]
    probs = model.probabilities(board, scored, 1000)
    assert sum(probs) == pytest.approx(1.0)
    assert probs[[m for m, _ in scored].index(take)] > 0.8
    rng = random.Random(0)
    hits = sum(model.choose(board, scored, 1000, rng) == take for _ in range(500))
    assert hits / 500 > 0.7
    # temperature > 1 makes mistakes more likely
    hot = model.probabilities(board, scored, 1000, temperature=4.0)
    assert hot[[m for m, _ in scored].index(take)] < probs[[m for m, _ in scored].index(take)]


def test_load_model_ignores_missing_and_mismatched_files(tmp_path):
    load_model.cache_clear()
    assert load_model(str(tmp_path / "nope.json")) is None
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"features": ["x"], "bands": {"1000": [0.0]}}))
    assert load_model(str(bad)) is None
    good = tmp_path / "good.json"
    humanmodel.save_model(good, {1000: [0.1] * len(FEATURE_NAMES)}, {})
    assert load_model(str(good)).weights_for(1000) == [0.1] * len(FEATURE_NAMES)
    load_model.cache_clear()


def test_fit_logit_recovers_known_weights():
    pytest.importorskip("scipy")
    import numpy as np
    rng = np.random.default_rng(0)
    d, n = 5, 6000
    true_w = np.array([-1.2, 0.5, 0.0, 0.8, -0.4])
    X, sizes, chosen = [], [], []
    for _ in range(n):
        k = int(rng.integers(5, 25))
        F = rng.normal(size=(k, d))
        p = np.exp(F @ true_w)
        p /= p.sum()
        chosen.append(int(rng.choice(k, p=p)))
        sizes.append(k)
        X.append(F)
    w = fit_human.fit_logit(np.vstack(X), sizes, chosen, l2=1e-5)
    assert np.allclose(w, true_w, atol=0.12)


def test_backend_uses_model_only_when_present(tmp_path, monkeypatch):
    load_model.cache_clear()
    w = [0.0] * len(FEATURE_NAMES)
    w[0] = -3.0
    path = tmp_path / "m.json"
    humanmodel.save_model(path, {1000: w}, {})
    monkeypatch.setattr(humanmodel, "MODEL_PATH", path)
    load_model.cache_clear()
    bot = make_backend(1000, use_book=False, use_model=True)
    board = chess.Board("rnbqkb1r/pppppppp/8/3n4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 1")
    random.seed(1)
    picks = [bot.choose_move(board) for _ in range(20)]
    assert sum(m == chess.Move.from_uci("e4d5") for m in picks) >= 17
    load_model.cache_clear()


def pgn(text):
    return iter(lambda: None, 1) if False else fit_human.iter_games([_write(text)])


_tmp = []


def _write(text):
    import tempfile
    f = tempfile.NamedTemporaryFile("w", suffix=".pgn", delete=False)
    f.write(text)
    f.close()
    _tmp.append(f.name)
    return f.name


GAME = """[WhiteElo "1000"]
[BlackElo "1050"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 *

[WhiteElo "1010"]
[BlackElo "1020"]

1. e4 e5 2. Nf3 Nf6 3. Nxe5 *

[WhiteElo "2500"]
[BlackElo "2500"]

1. d4 d5 *
"""


def test_human_book_filters_by_rating_and_count():
    book = fit_human.build_human_book(pgn(GAME), 900, 1500, plies=6, min_count=1, min_share=0.0)
    start = " ".join(chess.STARTING_FEN.split()[:4])
    assert set(book[start]) == {"e2e4"}          # the 2500 game's d4 is excluded
    after_nf3 = chess.Board()
    for san in ("e4", "e5", "Nf3"):
        after_nf3.push_san(san)
    key = " ".join(after_nf3.fen().split()[:4])
    assert book[key] == {"b8c6": 1, "g8f6": 1}
    strict = fit_human.build_human_book(pgn(GAME), 900, 1500, plies=6, min_count=2, min_share=0.0)
    assert set(strict[key] if key in strict else {}) == set()   # each reply seen once only


def test_extract_samples_respects_bands_and_skip():
    bands = [(900, 1005), (1005, 1100)]
    samples, taken = fit_human.extract_samples(pgn(GAME), bands, skip_plies=2, min_clock=0, max_per_band=100)
    assert taken[0] > 0 and taken[1] > 0
    assert all(chess.Board(fen).ply() >= 2 for _, fen, _, _ in samples)
    assert not any(chess.Board(fen).ply() < 2 for _, fen, _, _ in samples)


EVAL_GAME = """[WhiteElo "1000"]
[BlackElo "2000"]

{ [%eval 0.2] } 1. e4 { [%eval 0.3] } e5 { [%eval 0.2] } 2. Nf3 { [%eval -3.0] } *
"""


def test_profile_counts_blunders_for_selected_side_only():
    r = fit_human.profile_games(pgn(EVAL_GAME), min_elo=900, max_elo=1100)
    allp = r["phases"]["all"]
    assert allp["moves"] == 2                    # white's two moves only
    assert allp["blunder_rate"] == 0.5
    assert allp["acpl"] == pytest.approx(160.0)


def test_profile_skips_games_without_evals():
    r = fit_human.profile_games(pgn(GAME), min_elo=900, max_elo=1100)
    assert r["games_used"] == 0 and r["games_skipped_no_eval"] == 2
