"""The interface every move provider (built-in engine, Stockfish, Maia...) implements."""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import chess


class Backend(Protocol):
    name: str

    def set_elo(self, elo: int) -> None:
        """Change the target strength."""

    def choose_move(self, board: "chess.Board") -> "chess.Move":
        """Return a legal move for the side to move. Must not modify `board`."""

    def close(self) -> None:
        """Release any resources (engine processes, etc.)."""
