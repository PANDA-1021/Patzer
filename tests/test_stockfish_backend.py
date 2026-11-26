"""StockfishBackend, tested against a fake engine (no Stockfish needed)."""
import types

import chess
import chess.engine
import pytest

from patzer.backends import BuiltinBackend, StockfishBackend, StockfishNotFound, make_player, uses_stockfish
from patzer.backends import stockfish as sf_module


class FakeEngine:
    instances = []

    def __init__(self):
        self.options, self.played, self.quit_calls, self.fail_next = {}, [], 0, False
        self.bad_move = None
        FakeEngine.instances.append(self)

    def configure(self, opts):
        self.options.update(opts)

    def play(self, board, limit):
        if self.fail_next:
            self.fail_next = False
            raise chess.engine.EngineTerminatedError("engine died")
        self.played.append((board.fen(), limit.time))
        move = self.bad_move or next(iter(board.legal_moves))
        return types.SimpleNamespace(move=move)

    def quit(self):
        self.quit_calls += 1


@pytest.fixture(autouse=True)
def _reset():
    FakeEngine.instances = []


def make(elo=1500, **kw):
    return StockfishBackend(elo, "fake/path", engine_factory=lambda path: FakeEngine(), **kw)


def test_limits_strength_to_the_requested_elo():
    bot = make(1500)
    opts = FakeEngine.instances[0].options
    assert opts["UCI_LimitStrength"] is True and opts["UCI_Elo"] == 1500


def test_elo_is_clamped_to_stockfishs_range():
    assert make(1000).elo == 1320
    assert make(5000).elo == 3190


def test_set_elo_reconfigures_the_running_engine():
    bot = make(1500)
    bot.set_elo(2000)
    assert FakeEngine.instances[0].options["UCI_Elo"] == 2000


def test_returns_a_legal_move_and_leaves_the_board_alone():
    bot = make(movetime=0.25)
    board = chess.Board()
    before = board.fen()
    move = bot.choose_move(board)
    assert move in board.legal_moves and board.fen() == before
    assert FakeEngine.instances[0].played[0][1] == 0.25


def test_restarts_the_engine_once_if_it_dies():
    bot = make()
    FakeEngine.instances[0].fail_next = True
    move = bot.choose_move(chess.Board())
    assert move in chess.Board().legal_moves
    assert len(FakeEngine.instances) == 2 and FakeEngine.instances[0].quit_calls == 1


def test_rejects_an_illegal_move_from_the_engine():
    bot = make()
    FakeEngine.instances[0].bad_move = chess.Move.from_uci("e2e5")
    with pytest.raises(RuntimeError):
        bot.choose_move(chess.Board())


def test_close_quits_the_engine_and_is_safe_to_repeat():
    bot = make()
    bot.close()
    bot.close()
    assert FakeEngine.instances[0].quit_calls == 1


def test_bad_path_fails_at_creation_not_on_the_first_move():
    def boom(path):
        raise FileNotFoundError(path)
    with pytest.raises(FileNotFoundError):
        StockfishBackend(1500, "nope", engine_factory=boom)


def test_routing_by_elo(monkeypatch):
    assert not uses_stockfish(1000) and uses_stockfish(1340)
    assert isinstance(make_player(1000), BuiltinBackend)
    with pytest.raises(StockfishNotFound):
        make_player(1500)
    monkeypatch.setattr(sf_module, "_default_factory", lambda path: FakeEngine())
    player = make_player(1500, "fake/path")
    assert isinstance(player, StockfishBackend) and player.elo == 1500
