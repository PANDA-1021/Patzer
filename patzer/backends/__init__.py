"""Move providers. `make_backend` picks the right one for a target Elo."""
from .base import Backend
from .builtin import BuiltinBackend


def make_backend(elo: int) -> Backend:
    # Later phases will return a Stockfish or Maia backend for some Elo ranges.
    return BuiltinBackend(elo)


__all__ = ["Backend", "BuiltinBackend", "make_backend"]
