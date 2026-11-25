"""Move providers. `make_backend` picks the right one for a target Elo."""
from .base import Backend
from .builtin import BuiltinBackend


def make_backend(elo: int, use_book: bool = True) -> Backend:
    # Later phases will return a Stockfish or Maia backend for some Elo ranges.
    return BuiltinBackend(elo, use_book=use_book)


__all__ = ["Backend", "BuiltinBackend", "make_backend"]
