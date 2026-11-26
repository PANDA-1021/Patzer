import pytest

from patzer import settings


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "home" / "settings.json")
    monkeypatch.delenv("STOCKFISH_PATH", raising=False)
    monkeypatch.setattr(settings.shutil, "which", lambda name: None)


def test_save_and_load_roundtrip():
    assert settings.load_settings() == {}
    settings.save_settings({"a": 1})
    assert settings.load_settings() == {"a": 1}


def test_corrupt_settings_file_is_ignored():
    settings.SETTINGS_PATH.parent.mkdir(parents=True)
    settings.SETTINGS_PATH.write_text("{not json", encoding="utf-8")
    assert settings.load_settings() == {}


def test_find_stockfish_prefers_env_then_saved_then_path(tmp_path, monkeypatch):
    env_exe, saved_exe, path_exe = (tmp_path / n for n in ("env.exe", "saved.exe", "path.exe"))
    for f in (env_exe, saved_exe, path_exe):
        f.write_text("x")
    assert settings.find_stockfish() is None
    monkeypatch.setattr(settings.shutil, "which", lambda name: str(path_exe))
    assert settings.find_stockfish() == str(path_exe)
    settings.remember_stockfish(str(saved_exe))
    assert settings.find_stockfish() == str(saved_exe)
    monkeypatch.setenv("STOCKFISH_PATH", str(env_exe))
    assert settings.find_stockfish() == str(env_exe)


def test_missing_files_are_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKFISH_PATH", str(tmp_path / "gone.exe"))
    settings.remember_stockfish(str(tmp_path / "also-gone.exe"))
    assert settings.find_stockfish() is None
