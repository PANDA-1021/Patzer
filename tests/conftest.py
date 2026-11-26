import pytest


@pytest.fixture(autouse=True)
def _legacy_behaviour_by_default(monkeypatch):
    """Older tests target the generic book and the hand-tuned picker; new tests opt in explicitly."""
    monkeypatch.setattr("patzer.config.HUMAN_MODEL_ENABLED", False)
    monkeypatch.setattr("patzer.config.REPERTOIRE_MODE", False)
