"""Opening repertoire, opening principles and the repertoire wrapper."""
import random
import textwrap

import chess
import pytest

from patzer import config
from patzer.backends import RepertoireBackend, make_backend
from patzer.engine import opening_sense
from patzer.engine.repertoire import get_repertoire, load_repertoire, repertoire_move
from patzer.engine.strength import pick_move, strength_params


def board_after(san: str) -> chess.Board:
    b = chess.Board()
    for s in san.split():
        b.push_san(s)
    return b


@pytest.fixture
def repertoire_mode(monkeypatch):
    monkeypatch.setattr(config, "REPERTOIRE_MODE", True)


def test_shipped_files_load_cleanly():
    rep = get_repertoire()
    assert rep.errors == []
    assert set(rep.files) == {"white_alien_gambit.pgn", "white_wayward_queen.pgn", "white_alapin_sicilian.pgn",
                              "black_scandinavian.pgn", "black_kings_indian.pgn"}
    assert rep.files["black_kings_indian.pgn"]["color"] == "Black"
    assert rep.files["white_alien_gambit.pgn"]["color"] == "White"


@pytest.mark.parametrize("san,expected", [
    ("", {"e2e4"}),
    ("e4 c6", {"d2d4"}),              # Alien Gambit
    ("e4 e5", {"d1h5"}),              # Wayward Queen
    ("e4 c5", {"c2c3"}),              # Alapin
    ("e4", {"d7d5"}),                 # Scandinavian
    ("d4", {"g8f6"}),                 # King's Indian setup
    ("d4 Nf6 c4", {"g7g6", "d7d6"}),   # both are King's Indian move orders
])
def test_first_replies(san, expected):
    rep = get_repertoire()
    assert set(rep.moves_for(board_after(san))) == expected


def test_alien_gambit_is_followed_through():
    rep = get_repertoire()
    prefix = "e4 c6 d4 d5 Nc3 dxe4 Nxe4 Nf6"
    assert set(rep.moves_for(board_after(prefix))) == {"e4g5"}
    assert set(rep.moves_for(board_after(prefix + " Ng5 h6"))) == {"g5f7"}
    assert set(rep.moves_for(board_after(prefix + " Ng5 h6 Nxf7 Kxf7"))) == {"g1f3"}


def test_uncovered_positions_are_out_of_theory():
    rep = get_repertoire()
    assert rep.moves_for(board_after("e4 e6")) == {}          # French: not chosen
    assert rep.moves_for(board_after("c4")) == {}             # not a d4 opening
    assert rep.moves_for(board_after("d4 Nf6 Bg5")) == {}     # Trompowsky: heuristics


def test_colour_files_never_leak():
    rep = get_repertoire()
    # After 1.e4 d5 it is White to move. That position only occurs in Black's Scandinavian file, so a
    # White bot must NOT find a theory move there.
    assert rep.moves_for(board_after("e4 d5")) == {}
    # And after 1.d4 Nf6 2.c4 g6 (White to move) likewise.
    assert rep.moves_for(board_after("d4 Nf6 c4 g6")) == {}


def test_every_theory_move_is_legal_and_deep():
    rep = get_repertoire()
    deepest = max(st["max_ply"] for st in rep.files.values())
    assert deepest >= 20
    # replay each stored move from its own file by re-walking: just check a sample line end to end
    b = board_after("d4 Nf6 c4 g6 Nc3 Bg7 e4 d6 Nf3 O-O Be2")     # Classical: Black to move
    options = rep.moves_for(b)
    assert "e7e5" in options and all(chess.Move.from_uci(u) in b.legal_moves for u in options)


def test_repertoire_move_limits():
    b = board_after("e4 c6")
    assert repertoire_move(b, max_plies=60) == chess.Move.from_uci("d2d4")
    assert repertoire_move(b, max_plies=2) is None             # depth cap
    assert repertoire_move(b, forget_prob=1.0) is None         # forgot
    assert repertoire_move(board_after("e4 e6")) is None


def write_pgn(tmp_path, name, text):
    (tmp_path / name).write_text(textwrap.dedent(text), encoding="utf-8")


def test_loader_weights_nags_and_colour(tmp_path):
    write_pgn(tmp_path, "white_x.pgn", """\
        [Event "x"]
        [Color "White"]

        1. e4 (1. d4 $1) (1. c4 $2) (1. Nf3) e5 *
        """)
    rep = load_repertoire(tmp_path)
    opts = rep.moves_for(chess.Board())
    assert opts == {"e2e4": 4, "d2d4": 3 * 1, "g1f3": 1}      # ! triples a side move, ? is banned
    write_pgn(tmp_path, "black_y.pgn", "1. e4 d5 *\n")       # colour from file name
    assert load_repertoire(tmp_path).moves_for(board_after("e4")) == {"d7d5": 4}
    write_pgn(tmp_path, "mystery.pgn", "1. e4 e5 *\n")
    assert any("Color" in e for e in load_repertoire(tmp_path).errors)


def test_loader_reports_illegal_moves(tmp_path):
    write_pgn(tmp_path, "white_bad.pgn", """\
        [Color "White"]

        1. e4 e5 2. Ke3 Ke6 3. Qxh7 *
        """)
    assert load_repertoire(tmp_path).errors


def test_transpositions_share_weight(tmp_path):
    write_pgn(tmp_path, "black_t.pgn", """\
        [Color "Black"]

        1. d4 Nf6 2. c4 g6 *

        [Color "Black"]

        1. c4 Nf6 2. d4 g6 *
        """)
    b = board_after("d4 Nf6 c4")
    assert load_repertoire(tmp_path).moves_for(b) == {"g7g6": 8}


def test_builtin_bot_plays_theory_then_thinks(repertoire_mode, monkeypatch):
    monkeypatch.setattr(config, "HUMAN_MODEL_ENABLED", False)
    random.seed(0)
    bot = make_backend(1000)
    assert {bot.choose_move(board_after("e4")) for _ in range(15)} == {chess.Move.from_uci("d7d5")}
    assert {bot.choose_move(board_after("e4 e5")) for _ in range(15)} == {chess.Move.from_uci("d1h5")}
    # out of theory: still a legal move, found by search
    b = board_after("e4 e6")
    assert bot.choose_move(b) in b.legal_moves


def test_book_ignored_when_repertoire_mode_off(monkeypatch):
    monkeypatch.setattr(config, "REPERTOIRE_MODE", False)
    random.seed(1)
    moves = {make_backend(1000).choose_move(chess.Board()) for _ in range(40)}
    assert len(moves) >= 2          # the old generic book mixes first moves


# ---- opening principles -------------------------------------------------
def test_principles_rank_sensible_moves():
    b = board_after("e4 e6")
    bonus = lambda u: opening_sense.move_bonus(b, chess.Move.from_uci(u))
    assert bonus("g1f3") > bonus("b1a3")           # develop toward the centre, not to the rim
    assert bonus("d2d4") > bonus("a2a4")
    assert bonus("e1e2") < 0                       # king walk gives up castling
    assert bonus("d1h5") < bonus("g1f3")           # early queen
    c = board_after("e4 e5 Nf3 Nc6 Bc4 Bc5")
    assert opening_sense.move_bonus(c, chess.Move.from_uci("e1g1")) > 30   # castling


def test_principles_fade_and_do_not_override_material():
    b = board_after("e4 e6")
    scored = [(m, 0.0) for m in b.legal_moves]
    assert any(s != 0 for _, s in opening_sense.adjust_scores(b, scored))
    late = chess.Board("r3k2r/pppq1ppp/2n5/3pp3/8/2N2N2/PPPPQPPP/R3K2R w KQkq - 0 20")
    assert [s for _, s in opening_sense.adjust_scores(late, [(m, 0.0) for m in late.legal_moves])] == \
        [0.0] * late.legal_moves.count()
    assert opening_sense.phase_weight(10) == 1.0 and opening_sense.phase_weight(36) == 0.0
    # a free knight is still taken
    free = chess.Board("rnbqkb1r/pppppppp/8/3n4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 1")
    random.seed(2)
    bot = make_backend(1000, use_book=False, use_model=False)
    assert sum(bot.choose_move(free) == chess.Move.from_uci("e4d5") for _ in range(30)) >= 27


def test_out_of_book_play_is_mostly_principled(repertoire_mode, monkeypatch):
    monkeypatch.setattr(config, "HUMAN_MODEL_ENABLED", False)
    random.seed(4)
    bot = make_backend(1000)
    b = board_after("e4 e6")
    picks = [bot.choose_move(b) for _ in range(60)]
    bad = sum(opening_sense.move_bonus(b, m) < 0 for m in picks)
    assert bad <= 6


def test_pick_move_prefers_better_moves_when_asked():
    params = strength_params(1000)._replace(blunder_prob=0.0, miss_prob=1.0, miss_window=100)
    scored = [("good", 0.0), ("ok", -50.0), ("worse", -100.0)]
    rng = random.Random(0)
    flat = [pick_move(scored, params, rng) for _ in range(600)]
    pref = [pick_move(scored, params, rng, prefer_scale=30.0) for _ in range(600)]
    assert pref.count("good") > flat.count("good") + 100


# ---- wrapper for Stockfish ----------------------------------------------
class Inner:
    name = "Fake"
    elo = 1500

    def __init__(self):
        self.calls = 0
        self.closed = False

    def set_elo(self, elo):
        self.elo = elo

    def choose_move(self, board):
        self.calls += 1
        return next(iter(board.legal_moves))

    def close(self):
        self.closed = True


def test_wrapper_uses_theory_then_falls_back():
    inner = Inner()
    bot = RepertoireBackend(inner)
    assert bot.choose_move(board_after("e4 c6")) == chess.Move.from_uci("d2d4") and inner.calls == 0
    b = board_after("e4 e6")
    assert bot.choose_move(b) in b.legal_moves and inner.calls == 1
    bot.set_elo(1800)
    assert bot.elo == 1800 and "repertoire" in bot.name
    bot.close()
    assert inner.closed
