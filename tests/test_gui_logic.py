"""The GUI's engine-selection logic, tested without opening a window."""
import types

import pytest

pytest.importorskip("tkinter")   # skipped on machines without tkinter

from patzer.backends import BuiltinBackend  # noqa: E402
from patzer.gui import app  # noqa: E402


class Recorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append(name)
            return self.returns.get(name)
        return record

    returns: dict = {}


@pytest.fixture
def env(monkeypatch):
    msg, dlg, saved = Recorder(), Recorder(), []
    msg.returns, dlg.returns = {}, {}
    monkeypatch.setattr(app, "messagebox", msg)
    monkeypatch.setattr(app, "filedialog", dlg)
    monkeypatch.setattr(app, "find_stockfish", lambda: None)
    monkeypatch.setattr(app, "remember_stockfish", saved.append)
    monkeypatch.setattr(app, "make_player", lambda elo, path=None: types.SimpleNamespace(elo=elo, path=path, name="fake"))
    return types.SimpleNamespace(msg=msg, dlg=dlg, saved=saved, monkeypatch=monkeypatch)


def build(elo, interactive):
    return app.ChessApp._build_player(types.SimpleNamespace(), elo, interactive)


def test_low_elo_never_needs_stockfish_or_dialogs(env):
    env.monkeypatch.setattr(app, "make_player", lambda elo, path=None: BuiltinBackend(elo))
    assert isinstance(build(1000, True), BuiltinBackend)
    assert env.msg.calls == [] and env.dlg.calls == []


def test_quiet_startup_without_stockfish_returns_none_and_asks_nothing(env):
    assert build(1500, interactive=False) is None
    assert env.msg.calls == [] and env.dlg.calls == []


def test_known_stockfish_is_used_without_asking(env):
    env.monkeypatch.setattr(app, "find_stockfish", lambda: "C:/sf.exe")
    player = build(1500, True)
    assert player.path == "C:/sf.exe" and env.dlg.calls == [] and env.saved == []


def test_user_locates_stockfish_and_it_is_remembered_after_it_starts(env):
    env.dlg.returns["askopenfilename"] = "C:/picked.exe"
    player = build(1500, True)
    assert player.path == "C:/picked.exe" and env.saved == ["C:/picked.exe"]
    assert "showinfo" in env.msg.calls


def test_cancelling_the_dialog_returns_none_and_saves_nothing(env):
    env.dlg.returns["askopenfilename"] = ""
    assert build(1500, True) is None and env.saved == []


def test_a_bad_executable_is_not_remembered(env):
    env.dlg.returns["askopenfilename"] = "C:/not-stockfish.exe"

    def boom(elo, path=None):
        raise OSError("not a chess engine")
    env.monkeypatch.setattr(app, "make_player", boom)
    assert build(1500, True) is None
    assert env.saved == [] and "showerror" in env.msg.calls
