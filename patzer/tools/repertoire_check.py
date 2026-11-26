"""Check and explore your repertoire.

    python -m patzer.tools.repertoire_check            # validate files, show coverage
    python -m patzer.tools.repertoire_check e4 c5      # what would the bot play after 1.e4 c5 ?
"""
from __future__ import annotations

import sys

import chess

from patzer.engine.repertoire import load_repertoire


def main(argv=None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    rep = load_repertoire()
    for name, st in rep.files.items():
        print(f"{name:34s} plays {st['color']:5s}  deepest line {st['max_ply']:3d} plies  ({st['new_moves']} bot moves)")
    for err in rep.errors:
        print("PROBLEM:", err)
    for color, label in ((chess.WHITE, "White"), (chess.BLACK, "Black")):
        print(f"{label}: {sum(len(v) for v in rep.tables[color].values())} theory moves in "
              f"{len(rep.tables[color])} positions")
    if argv:
        board = chess.Board()
        try:
            for san in argv:
                board.push_san(san)
        except ValueError as exc:
            sys.exit(f"bad move: {exc}")
        options = rep.moves_for(board)
        if not options:
            print("Out of theory here: the engine + opening principles take over.")
        else:
            total = sum(options.values())
            for uci, w in sorted(options.items(), key=lambda kv: -kv[1]):
                print(f"  {board.san(chess.Move.from_uci(uci)):8s} {w / total:5.0%}")
    if rep.errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
