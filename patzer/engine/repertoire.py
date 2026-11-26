"""Your opening repertoire: theory the bot plays move by move, for the openings you chose.

The repertoire is a folder of PGN files (patzer/data/repertoire/*.pgn), one per opening, written the
way chess programs and Lichess studies export them: the main line plus variations. Every file
declares which side the bot plays it with:

    [Color "White"]        (or "Black")

Rules
  * Only the bot's own moves are learned from a file; the opponent's moves are just the branches it
    must be ready for. A Black file can never make the bot play White moves, and vice versa.
  * The first move at each branch is the preferred one (weight 4), later alternatives get weight 1.
    Mark a move with ! (NAG $1) or !! to triple its weight, or with ? / ?? to ban it.
  * Positions are matched by board position, so transpositions are found automatically.
  * Add an opening by dropping another PGN in the folder (e.g. export a Lichess study). No code changes.

If the opponent leaves the repertoire the bot is "out of book" and the engine takes over
(see opening_sense.py for the development / centre / king-safety guidance it uses there).
"""
from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import chess
import chess.pgn

from .book import position_key

REPERTOIRE_DIR = Path(__file__).resolve().parent.parent / "data" / "repertoire"
MAIN_WEIGHT = 4
SIDE_WEIGHT = 1
NAG_GOOD, NAG_MISTAKE, NAG_BRILLIANT, NAG_BLUNDER = 1, 2, 3, 4


@dataclass
class Repertoire:
    # colour -> position key -> {uci move: weight}
    tables: dict[bool, dict[str, dict[str, int]]] = field(
        default_factory=lambda: {chess.WHITE: {}, chess.BLACK: {}})
    errors: list[str] = field(default_factory=list)
    files: dict[str, dict] = field(default_factory=dict)   # file name -> stats

    def moves_for(self, board: chess.Board) -> dict[str, int]:
        return self.tables[board.turn].get(position_key(board), {})


def _file_color(game: chess.pgn.Game, path: Path) -> bool | None:
    tag = game.headers.get("Color", "").strip().lower()
    if not tag:
        tag = path.stem.lower().split("_")[0]
    return {"white": chess.WHITE, "black": chess.BLACK}.get(tag)


def _walk(node: chess.pgn.GameNode, board: chess.Board, color: bool,
          table: dict[str, dict[str, int]], stats: dict) -> None:
    kids = node.variations
    if board.turn == color:
        for i, child in enumerate(kids):
            w = MAIN_WEIGHT if i == 0 else SIDE_WEIGHT
            if NAG_MISTAKE in child.nags or NAG_BLUNDER in child.nags:
                continue
            if NAG_GOOD in child.nags or NAG_BRILLIANT in child.nags:
                w *= 3
            entry = table.setdefault(position_key(board), {})
            entry[child.move.uci()] = entry.get(child.move.uci(), 0) + w
    for child in kids:
        board.push(child.move)
        stats["max_ply"] = max(stats["max_ply"], board.ply())
        _walk(child, board, color, table, stats)
        board.pop()


def load_repertoire(directory: str | Path | None = None) -> Repertoire:
    rep = Repertoire()
    folder = Path(directory) if directory else REPERTOIRE_DIR
    for path in sorted(folder.glob("*.pgn")):
        with open(path, encoding="utf-8") as fh:
            while True:
                game = chess.pgn.read_game(fh)
                if game is None:
                    break
                color = _file_color(game, path)
                if color is None:
                    rep.errors.append(f'{path.name}: add a [Color "White"] or [Color "Black"] header')
                    continue
                for err in game.errors:
                    rep.errors.append(f"{path.name}: {err}")
                stats = {"max_ply": 0, "color": "White" if color else "Black"}
                before = sum(len(v) for v in rep.tables[color].values())
                _walk(game, game.board(), color, rep.tables[color], stats)
                stats["new_moves"] = sum(len(v) for v in rep.tables[color].values()) - before
                rep.files[path.name] = stats
    return rep


@lru_cache(maxsize=1)
def get_repertoire() -> Repertoire:
    return load_repertoire()


def repertoire_move(board: chess.Board, max_plies: int = 60, forget_prob: float = 0.0,
                    rng: random.Random | None = None, rep: Repertoire | None = None) -> chess.Move | None:
    """The bot's next theory move for `board`, or None if out of the repertoire."""
    rng = rng if rng is not None else random
    if board.ply() >= max_plies:
        return None
    options = (rep or get_repertoire()).moves_for(board)
    if not options or rng.random() < forget_prob:
        return None
    moves, weights = [], []
    for uci, w in options.items():
        move = chess.Move.from_uci(uci)
        if move in board.legal_moves:
            moves.append(move)
            weights.append(w)
    return rng.choices(moves, weights=weights, k=1)[0] if moves else None
