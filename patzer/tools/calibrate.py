"""
Calibration harness: measure how strong each bot Elo setting really plays.

It plays the bot against Stockfish (limited with UCI_Elo) or against another
bot setting, alternates colours on identical random openings, and converts the
match score into an Elo estimate with a 95% confidence interval.

Examples (run from the project folder):
    python -m patzer.tools.calibrate --games 2 --workers 1 --bot-elo 1340      # quick smoke test
    python -m patzer.tools.calibrate --bot-elo 1340 1500 1700 --games 40
    python -m patzer.tools.calibrate --bot-elo 1000 --opp-bot 1340 --opp-rating 1340 --games 40

Notes
  * Stockfish's UCI_Elo floor is 1320. A bot far below the opponent scores ~0%,
    which makes the estimate unreliable (it is flagged "saturated"). To measure
    low settings, anchor a stronger setting against Stockfish first, then play
    the low setting against that anchor with --opp-bot / --opp-rating.
  * Stockfish's Elo labels assume long time controls. With short --movetime it
    plays weaker than labelled, so treat results as a consistent relative scale,
    not an exact Lichess/chess.com rating.
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import random
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import chess
import chess.engine
import chess.pgn

from patzer.backends import make_backend
from patzer.tools.stats import summarize

# Set the STOCKFISH_PATH environment variable once, or pass --stockfish each time.
DEFAULT_STOCKFISH = os.environ.get("STOCKFISH_PATH") or shutil.which("stockfish") or ""
SF_MIN_ELO, SF_MAX_ELO = 1320, 3190


# ----------------------------------------------------------------- one game --
def play_game(task: dict) -> tuple[float, str]:
    """Play one game. Returns (score from the bot's point of view, PGN text)."""
    random.seed(task["seed"])
    board = chess.Board(task["fen"])
    bot = make_backend(task["bot_elo"])
    bot_color = task["bot_color"]
    opp = task["opp"]

    engine = opp_bot = limit = None
    if opp["kind"] == "stockfish":
        engine = chess.engine.SimpleEngine.popen_uci(opp["path"])
        engine.configure({"Threads": 1, "Hash": 16,
                          "UCI_LimitStrength": True, "UCI_Elo": opp["elo"]})
        limit = chess.engine.Limit(time=task["movetime"])
    else:
        opp_bot = make_backend(opp["setting"])

    try:
        plies = 0
        while not board.is_game_over(claim_draw=True) and plies < task["max_plies"]:
            if board.turn == bot_color:
                move = bot.choose_move(board)
            elif engine is not None:
                move = engine.play(board, limit).move
            else:
                move = opp_bot.choose_move(board)
            board.push(move)
            plies += 1
    finally:
        if engine is not None:
            engine.quit()

    finished = board.is_game_over(claim_draw=True)
    result = board.result(claim_draw=True) if finished else "1/2-1/2"  # adjudicate long games
    bot_white = bot_color == chess.WHITE
    if result == "1-0":
        score = 1.0 if bot_white else 0.0
    elif result == "0-1":
        score = 0.0 if bot_white else 1.0
    else:
        score = 0.5

    game = chess.pgn.Game.from_board(board)
    bot_name = f"Bot@{task['bot_elo']}"
    opp_name = f"Stockfish@{opp['elo']}" if opp["kind"] == "stockfish" else f"Bot@{opp['setting']}"
    game.headers["White"] = bot_name if bot_white else opp_name
    game.headers["Black"] = opp_name if bot_white else bot_name
    game.headers["Result"] = result
    if not finished:
        game.headers["Termination"] = "adjudicated draw (move limit)"
    return score, str(game)


def random_opening(plies: int, rng: random.Random) -> str:
    while True:
        b = chess.Board()
        for _ in range(plies):
            if b.is_game_over():
                break
            b.push(rng.choice(list(b.legal_moves)))
        if not b.is_game_over():
            return b.fen()


# --------------------------------------------------------------------- main --
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bot-elo", type=int, nargs="+", default=[1340],
                    help="bot settings to test (default: 1340)")
    ap.add_argument("--games", type=int, default=20, help="games per setting; rounded up to even")
    ap.add_argument("--stockfish", default=DEFAULT_STOCKFISH, help="path to the Stockfish executable (default: $STOCKFISH_PATH, then PATH)")
    ap.add_argument("--sf-elo", type=int, default=SF_MIN_ELO, help="Stockfish UCI_Elo (1320-3190)")
    ap.add_argument("--movetime", type=float, default=0.1, help="Stockfish seconds per move")
    ap.add_argument("--opp-bot", type=int, default=None,
                    help="play against another bot setting instead of Stockfish")
    ap.add_argument("--opp-rating", type=float, default=None,
                    help="assumed true rating of the --opp-bot opponent (default: its setting)")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2),
                    help="parallel games (default: half your CPU cores)")
    ap.add_argument("--random-plies", type=int, default=4, help="random opening plies per game pair")
    ap.add_argument("--max-plies", type=int, default=300, help="adjudicate a draw after this many plies")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--csv", default="calibration_results.csv")
    ap.add_argument("--pgn", default=None, help="optional file to append all games to (for game review)")
    return ap.parse_args()


def main() -> None:
    args = parse_args()

    if args.opp_bot is not None:
        opp = {"kind": "bot", "setting": args.opp_bot}
        opp_rating = args.opp_rating if args.opp_rating is not None else float(args.opp_bot)
        opp_label = f"Bot@{args.opp_bot} (assumed {opp_rating:.0f})"
    else:
        if not args.stockfish or not Path(args.stockfish).is_file():
            sys.exit(f"Stockfish not found (looked for: {args.stockfish or 'nothing'}).\n"
                     "Pass the path with --stockfish, or set the STOCKFISH_PATH environment variable.")
        sf_elo = max(SF_MIN_ELO, min(SF_MAX_ELO, args.sf_elo))
        if sf_elo != args.sf_elo:
            print(f"Note: --sf-elo clamped to {sf_elo} (Stockfish supports {SF_MIN_ELO}-{SF_MAX_ELO}).")
        opp = {"kind": "stockfish", "path": args.stockfish, "elo": sf_elo}
        opp_rating = float(sf_elo)
        opp_label = f"Stockfish UCI_Elo {sf_elo} @ {args.movetime}s/move"

    pairs = max(1, math.ceil(args.games / 2))
    rng = random.Random(args.seed)
    print(f"Opponent: {opp_label}")
    print(f"{pairs * 2} games per setting, {args.workers} worker(s)\n")

    csv_path = Path(args.csv)
    new_csv = not csv_path.exists()

    for bot_elo in args.bot_elo:
        tasks = []
        for _ in range(pairs):
            fen = random_opening(args.random_plies, rng)
            for color in (chess.WHITE, chess.BLACK):
                tasks.append({"bot_elo": bot_elo, "bot_color": color, "fen": fen, "opp": opp,
                              "movetime": args.movetime, "max_plies": args.max_plies,
                              "seed": rng.randrange(1 << 30)})

        print(f"=== Bot setting {bot_elo} ===")
        scores: list[float] = []
        pgns: list[str] = []
        started = time.time()
        ex = ProcessPoolExecutor(max_workers=args.workers)
        try:
            futures = [ex.submit(play_game, t) for t in tasks]
            for fut in as_completed(futures):
                score, pgn = fut.result()
                scores.append(score)
                pgns.append(pgn)
                w = sum(1 for s in scores if s == 1.0)
                d = sum(1 for s in scores if s == 0.5)
                print(f"  game {len(scores):>3}/{len(tasks)}   W{w} D{d} L{len(scores) - w - d}   "
                      f"({time.time() - started:.0f}s)", flush=True)
        except KeyboardInterrupt:
            print("\nInterrupted - summarising the games finished so far.")
            ex.shutdown(wait=False, cancel_futures=True)
        else:
            ex.shutdown()

        if not scores:
            break
        r = summarize(scores, opp_rating)
        print(f"  Result: +{r['wins']} ={r['draws']} -{r['losses']}  score {r['score']:.1%}")
        print(f"  Estimated Elo: {r['elo']:.0f}  (95% CI {r['elo_low']:.0f} to {r['elo_high']:.0f})")
        if r["saturated"]:
            print("  WARNING: score is near 0% or 100%, so the opponent is too far away to measure "
                  "this setting reliably. Use a closer opponent (see the notes at the top of this file).")
        print()

        with csv_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if new_csv:
                writer.writerow(["timestamp", "bot_setting", "opponent", "games", "wins", "draws",
                                 "losses", "score", "est_elo", "ci_low", "ci_high", "saturated"])
                new_csv = False
            writer.writerow([datetime.now().isoformat(timespec="seconds"), bot_elo, opp_label,
                             r["games"], r["wins"], r["draws"], r["losses"], f"{r['score']:.3f}",
                             f"{r['elo']:.0f}", f"{r['elo_low']:.0f}", f"{r['elo_high']:.0f}", r["saturated"]])
        if args.pgn:
            with open(args.pgn, "a", encoding="utf-8") as f:
                f.write("\n\n".join(pgns) + "\n\n")

    print(f"Results saved to {csv_path}" + (f"; games saved to {args.pgn}" if args.pgn else ""))


if __name__ == "__main__":  # required for multiprocessing on Windows
    main()