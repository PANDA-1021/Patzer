"""Move providers. `make_player` picks the right one for a target Elo."""
from patzer import config
from patzer.config import STOCKFISH_MIN_ELO

from .base import Backend
from .builtin import BuiltinBackend
from .repertoire import RepertoireBackend
from .stockfish import StockfishBackend, StockfishNotFound


def make_backend(elo: int, use_book: bool = True, use_model: bool | None = None) -> Backend:
    """The built-in engine at a given setting (used by the calibration tools)."""
    return BuiltinBackend(elo, use_book=use_book, use_model=use_model)


def uses_stockfish(elo: int) -> bool:
    return elo >= STOCKFISH_MIN_ELO


def make_player(elo: int, stockfish_path: str | None = None) -> Backend:
    """What the app plays against: the built-in engine below 1320, Stockfish at 1320 and up."""
    if uses_stockfish(elo):
        if not stockfish_path:
            raise StockfishNotFound(f"A rating of {elo} needs Stockfish, but no Stockfish path is set.")
        player = StockfishBackend(elo, stockfish_path)
        return RepertoireBackend(player) if config.REPERTOIRE_MODE else player
    return BuiltinBackend(elo)


__all__ = ["Backend", "BuiltinBackend", "StockfishBackend", "StockfishNotFound",
           "RepertoireBackend", "make_backend", "make_player", "uses_stockfish"]
