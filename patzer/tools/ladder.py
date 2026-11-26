"""
Ladder calibration: measure every bot setting in ONE run and fit a single Elo table.

Instead of testing one setting at a time, this plays neighbouring settings against
each other (and optionally against Stockfish), then fits one rating per setting by
maximum likelihood. Stockfish (or one chosen setting) fixes the absolute scale.

Examples (run from the project folder):
    # quick check that everything works, bot vs bot only, no Stockfish needed
    python -m patzer.tools.ladder --settings 400 1000 --games 4 --workers 1 --max-plies 100

    # the real thing: anchor the table to Stockfish at 1320 using the settings closest to it
    python -m patzer.tools.ladder --settings 400 700 1000 1340 1500 1700 --games 40 \
        --vs-stockfish 1340 1500 --sf-elo 1320 --pgn ladder_games.pgn

Output: a printed table, ladder_results.csv (history) and strength_table.json (latest).

Notes
  * Each setting plays the next --neighbors settings above it, so a chain of results
    links the weakest to the strongest. Wide gaps near 0% / 100% are flagged.
  * Stockfish's Elo labels assume long time controls; at short --movetime it plays
    weaker than labelled. Treat the table as a consistent relative scale.
  * Without --vs-stockfish the lowest setting is anchored at its own label, so the
    table is relative only.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import chess

from patzer.tools.calibrate import DEFAULT_STOCKFISH, SF_MAX_ELO, SF_MIN_ELO, play_game, random_opening
from patzer.tools.stats import fit_ratings


def player_name(kind: str, value: int) -> str:
    return f"bot:{value}" if kind == "bot" else f"sf:{value}"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--settings", type=int, nargs="+", required=True, help="bot settings (Elo labels) to measure")
    ap.add_argument("--games", type=int, default=20, help="games per pairing; rounded up to even")
    ap.add_argument("--neighbors", type=int, default=2, help="each setting plays the next N settings above it")
    ap.add_argument("--vs-stockfish", type=int, nargs="*", default=[], help="settings that also play Stockfish")
    ap.add_argument("--sf-elo", type=int, default=SF_MIN_ELO, help="Stockfish UCI_Elo (1320-3190)")
    ap.add_argument("--stockfish", default=DEFAULT_STOCKFISH, help="Stockfish path (default: $STOCKFISH_PATH, then PATH)")
    ap.add_argument("--movetime", type=float, default=0.1, help="Stockfish seconds per move")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    ap.add_argument("--random-plies", type=int, default=4)
    ap.add_argument("--max-plies", type=int, default=300)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--csv", default="ladder_results.csv")
    ap.add_argument("--json", default="strength_table.json")
    ap.add_argument("--pgn", default=None, help="optional file to append all games to")
    return ap.parse_args()


def plan_pairings(settings: list[int], neighbors: int, vs_stockfish: list[int], sf_elo: int):
    """Return [(player_a, spec_a, player_b, spec_b)] where spec is the opponent dict for play_game."""
    ordered = sorted(set(settings))
    pairs = []
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:i + 1 + neighbors]:
            pairs.append((a, {"kind": "bot", "setting": b}, player_name("bot", a), player_name("bot", b)))
    for a in sorted(set(vs_stockfish)):
        pairs.append((a, None, player_name("bot", a), player_name("sf", sf_elo)))
    return pairs


def main() -> None:
    args = parse_args()
    settings = sorted(set(args.settings))

    sf_spec = None
    if args.vs_stockfish:
        unknown = [s for s in args.vs_stockfish if s not in settings]
        if unknown:
            sys.exit(f"--vs-stockfish settings must also be in --settings: {unknown}")
        if not args.stockfish or not Path(args.stockfish).is_file():
            sys.exit(f"Stockfish not found (looked for: {args.stockfish or 'nothing'}).\n"
                     "Pass --stockfish, or set the STOCKFISH_PATH environment variable.")
        sf_elo = max(SF_MIN_ELO, min(SF_MAX_ELO, args.sf_elo))
        sf_spec = {"kind": "stockfish", "path": args.stockfish, "elo": sf_elo}
        anchors = {player_name("sf", sf_elo): float(sf_elo)}
        anchor_text = f"Stockfish UCI_Elo {sf_elo} @ {args.movetime}s/move"
    else:
        sf_elo = args.sf_elo
        low = settings[0]
        anchors = {player_name("bot", low): float(low)}
        anchor_text = f"relative only: bot:{low} fixed at {low}"

    rng = random.Random(args.seed)
    pairs_per_matchup = max(1, math.ceil(args.games / 2))
    tasks = []   # (key, task dict)
    for a, spec, name_a, name_b in plan_pairings(settings, args.neighbors, args.vs_stockfish, sf_elo):
        opp = spec if spec is not None else sf_spec
        for _ in range(pairs_per_matchup):
            fen = random_opening(args.random_plies, rng)
            for color in (chess.WHITE, chess.BLACK):
                tasks.append(((name_a, name_b), {
                    "bot_elo": a, "bot_color": color, "fen": fen, "opp": opp,
                    "movetime": args.movetime, "max_plies": args.max_plies,
                    "seed": rng.randrange(1 << 30)}))
    rng.shuffle(tasks)   # spread slow (deep) games evenly across workers

    print(f"Anchor: {anchor_text}")
    print(f"{len(tasks)} games in total, {args.workers} worker(s)\n", flush=True)

    totals: dict[tuple[str, str], list[float]] = {}   # key -> [points for a, games]
    pgns: list[str] = []
    started = time.time()
    ex = ProcessPoolExecutor(max_workers=args.workers)
    try:
        futures = {ex.submit(play_game, t): key for key, t in tasks}
        done = 0
        for fut in as_completed(futures):
            key = futures[fut]
            score, pgn, _ended, _plies = fut.result()
            rec = totals.setdefault(key, [0.0, 0])
            rec[0] += score
            rec[1] += 1
            pgns.append(pgn)
            done += 1
            if done % 5 == 0 or done == len(tasks):
                print(f"  {done}/{len(tasks)} games done ({time.time() - started:.0f}s)", flush=True)
    except KeyboardInterrupt:
        print("\nInterrupted - fitting the games finished so far.")
        ex.shutdown(wait=False, cancel_futures=True)
    else:
        ex.shutdown()

    if not totals:
        sys.exit("No games finished.")

    results = {k: (v[0], int(v[1])) for k, v in totals.items()}
    print("\nHead-to-head results (points for the first player):")
    for (a, b), (pts, n) in sorted(results.items()):
        flag = "   <- near 0%/100%, weak evidence" if pts / n < 0.1 or pts / n > 0.9 else ""
        print(f"  {a:>9} vs {b:<9} {pts:5.1f}/{n:<3} ({pts / n:5.1%}){flag}")

    fit = fit_ratings(results, anchors)
    print(f"\nFitted ratings (anchor: {anchor_text})")
    print(f"  {'setting':>8} {'Elo':>6} {'+/- 95%':>8}")
    table = {}
    for name, (rating, se) in sorted(fit.items(), key=lambda kv: kv[1][0]):
        if not name.startswith("bot:"):
            print(f"  {name:>8} {rating:6.0f}   (anchor)")
            continue
        setting = int(name.split(":")[1])
        table[setting] = {"elo": round(rating), "ci95": round(1.96 * se)}
        print(f"  {setting:>8} {rating:6.0f} {'+/-' + str(round(1.96 * se)):>8}")

    now = datetime.now().isoformat(timespec="seconds")
    csv_path = Path(args.csv)
    new_csv = not csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_csv:
            w.writerow(["timestamp", "setting", "elo", "ci95", "anchor", "games_per_pairing"])
        for setting, row in sorted(table.items()):
            w.writerow([now, setting, row["elo"], row["ci95"], anchor_text, pairs_per_matchup * 2])
    Path(args.json).write_text(json.dumps(
        {"timestamp": now, "anchor": anchor_text, "ratings": {str(k): v for k, v in sorted(table.items())}},
        indent=2), encoding="utf-8")
    if args.pgn:
        with open(args.pgn, "a", encoding="utf-8") as f:
            f.write("\n\n".join(pgns) + "\n\n")
    print(f"\nSaved {args.json} and {csv_path}" + (f"; games in {args.pgn}" if args.pgn else ""))


if __name__ == "__main__":  # required for multiprocessing on Windows
    main()
