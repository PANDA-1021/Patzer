"""Learn human-like play from real games.

Three commands (run from the project folder):

  book     mine an opening book from human games
             python -m patzer.tools.fit_human book lichess.pgn --min-elo 900 --max-elo 1500

  train    fit the human move-choice model, one weight vector per rating band
             python -m patzer.tools.fit_human train lichess.pgn --bands 900-1100 1100-1300 1300-1500

  profile  measure how many inaccuracies / mistakes / blunders a set of players make
           (use it on human games AND on the bot's own games, then compare the two)
             python -m patzer.tools.fit_human profile lichess.pgn --min-elo 900 --max-elo 1100
             python -m patzer.tools.fit_human profile ladder_games.pgn --name "Bot@1000" --stockfish /path/sf

Input is plain PGN (.pgn, .pgn.gz, .pgn.bz2). Lichess monthly dumps come as .pgn.zst: unpack
them first with `zstd -d`. Only a small share of Lichess games carry [%eval] annotations; for
`profile`, games without them are analysed with Stockfish if --stockfish is given, else skipped.

Training needs numpy and scipy (pip install numpy scipy); playing the app does not.
"""
from __future__ import annotations

import argparse
import bz2
import gzip
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from multiprocessing import Pool
from pathlib import Path

import chess
import chess.engine
import chess.pgn

from patzer.engine.book import HUMAN_BOOK_PATH, position_key
from patzer.engine.evaluation import PIECE_VALUES
from patzer.engine.humanmodel import FEATURE_NAMES, MODEL_PATH, move_features, save_model
from patzer import config
from patzer.engine.opening_sense import adjust_scores
from patzer.engine.search import score_root_moves
from patzer.engine.strength import strength_params


# ---------------------------------------------------------------------------
# PGN helpers
# ---------------------------------------------------------------------------
def open_text(path: str):
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    if path.endswith(".bz2"):
        return bz2.open(path, "rt", encoding="utf-8", errors="replace")
    if path.endswith(".zst"):
        sys.exit(f"{path}: unpack with `zstd -d` first.")
    return open(path, "rt", encoding="utf-8", errors="replace")


def iter_games(paths):
    for path in paths:
        with open_text(path) as fh:
            while True:
                try:
                    game = chess.pgn.read_game(fh)
                except Exception:
                    continue
                if game is None:
                    break
                yield game


def side_elo(game: chess.pgn.Game, color: bool, assume: int | None) -> int | None:
    raw = game.headers.get("WhiteElo" if color == chess.WHITE else "BlackElo", "")
    return int(raw) if raw.isdigit() else assume


def parse_bands(specs: list[str]) -> list[tuple[int, int]]:
    bands = []
    for spec in specs:
        m = re.fullmatch(r"(\d+)-(\d+)", spec)
        if not m or int(m[1]) >= int(m[2]):
            raise SystemExit(f"bad band '{spec}': use LOW-HIGH, e.g. 900-1100")
        bands.append((int(m[1]), int(m[2])))
    return sorted(bands)


def band_index(elo: int | None, bands: list[tuple[int, int]]) -> int | None:
    if elo is None:
        return None
    for i, (lo, hi) in enumerate(bands):
        if lo <= elo < hi:
            return i
    return None


# ---------------------------------------------------------------------------
# book
# ---------------------------------------------------------------------------
def build_human_book(games, min_elo: int, max_elo: int, plies: int, min_count: int,
                     min_share: float, assume_elo: int | None = None) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter] = defaultdict(Counter)
    for game in games:
        we, be = side_elo(game, chess.WHITE, assume_elo), side_elo(game, chess.BLACK, assume_elo)
        if we is None or be is None or not (min_elo <= we <= max_elo and min_elo <= be <= max_elo):
            continue
        if game.headers.get("FEN") not in (None, chess.STARTING_FEN):
            continue
        board = game.board()
        for node in game.mainline():
            if board.ply() >= plies:
                break
            counts[position_key(board)][node.move.uci()] += 1
            board.push(node.move)
    book: dict[str, dict[str, int]] = {}
    for key, moves in counts.items():
        total = sum(moves.values())
        kept = {m: c for m, c in moves.items() if c >= min_count and c / total >= min_share}
        if kept:
            book[key] = kept
    return book


def cmd_book(args) -> None:
    book = build_human_book(iter_games(args.pgn), args.min_elo, args.max_elo, args.plies,
                            args.min_count, args.min_share, args.assume_elo)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(book), encoding="utf-8")
    print(f"{len(book)} book positions written to {out}")


# ---------------------------------------------------------------------------
# train
# ---------------------------------------------------------------------------
def extract_samples(games, bands, skip_plies: int, min_clock: float, max_per_band: int,
                    assume_elo: int | None = None):
    """[(band index, fen before the move, previous move uci or '', move uci)]."""
    samples, taken = [], [0] * len(bands)
    for game in games:
        board = game.board()
        last = ""
        for node in game.mainline():
            move = node.move
            b = band_index(side_elo(game, board.turn, assume_elo), bands)
            clk = node.clock()
            hurried = min_clock > 0 and clk is not None and clk < min_clock
            if (b is not None and taken[b] < max_per_band and board.ply() >= skip_plies
                    and not hurried and board.legal_moves.count() > 1):
                samples.append((b, board.fen(), last, move.uci()))
                taken[b] += 1
            board.push(move)
            last = move.uci()
        if all(t >= max_per_band for t in taken):
            break
    return samples, taken


def _featurize(job):
    fen, last_uci, move_uci, depth = job
    board = chess.Board(fen)
    last = chess.Move.from_uci(last_uci) if last_uci else None
    scored = score_root_moves(board, depth)
    if config.OPENING_SENSE > 0:   # same view of the position the bot has when playing
        scored = adjust_scores(board, scored, config.OPENING_SENSE)
    best = max(s for _, s in scored)
    target = chess.Move.from_uci(move_uci)
    idx = next((i for i, (m, _) in enumerate(scored) if m == target), None)
    if idx is None:
        return None
    rows = [move_features(board, m, best - s, last) for m, s in scored]
    return rows, idx


def fit_logit(X, sizes, chosen, l2: float = 1e-3, w0=None):
    """Maximum-likelihood conditional logit. X: rows of candidate features, grouped by position."""
    import numpy as np
    from scipy.optimize import minimize

    X = np.asarray(X, dtype=float)
    sizes = np.asarray(sizes)
    n = len(sizes)
    starts = np.concatenate([[0], np.cumsum(sizes)[:-1]])
    gid = np.repeat(np.arange(n), sizes)
    pick = starts + np.asarray(chosen)
    target_sum = X[pick].sum(axis=0)

    def fun(w):
        z = X @ w
        m = np.maximum.reduceat(z, starts)
        e = np.exp(z - m[gid])
        s = np.add.reduceat(e, starts)
        nll = (m + np.log(s) - z[pick]).sum() / n + 0.5 * l2 * (w @ w)
        grad = (X.T @ (e / s[gid]) - target_sum) / n + l2 * w
        return nll, grad

    w0 = np.zeros(X.shape[1]) if w0 is None else w0
    res = minimize(fun, w0, jac=True, method="L-BFGS-B")
    return res.x


def evaluate_logit(w, X, sizes, chosen) -> dict:
    import numpy as np
    X = np.asarray(X, dtype=float)
    sizes = np.asarray(sizes)
    starts = np.concatenate([[0], np.cumsum(sizes)[:-1]])
    z = X @ w
    m = np.maximum.reduceat(z, starts)
    s = np.add.reduceat(np.exp(z - np.repeat(m, sizes)), starts)
    pick = starts + np.asarray(chosen)
    nll = float((m + np.log(s) - z[pick]).mean())
    top1 = float(np.mean([np.argmax(z[a:a + k]) == c for a, k, c in zip(starts, sizes, chosen)]))
    uniform = float(np.mean(np.log(sizes)))
    gap_col = FEATURE_NAMES.index("gap")
    engine_best = float(np.mean([np.argmin(X[a:a + k, gap_col]) == c for a, k, c in zip(starts, sizes, chosen)]))
    return {"nll": round(nll, 4), "uniform_nll": round(uniform, 4),
            "top1_model": round(top1, 4), "top1_engine_best": round(engine_best, 4)}


def cmd_train(args) -> None:
    import numpy as np  # noqa: F401  (fail early with a clear message if missing)
    bands = parse_bands(args.bands)
    print("Reading games...")
    samples, taken = extract_samples(iter_games(args.pgn), bands, args.skip_plies, args.min_clock,
                                     args.max_per_band, args.assume_elo)
    for (lo, hi), n in zip(bands, taken):
        print(f"  band {lo}-{hi}: {n} positions")
    weights, meta_bands = {}, {}
    for i, (lo, hi) in enumerate(bands):
        centre = (lo + hi) // 2
        depth = strength_params(centre).depth
        jobs = [(fen, last, mv, depth) for b, fen, last, mv in samples if b == i]
        if len(jobs) < args.min_positions:
            print(f"band {lo}-{hi}: only {len(jobs)} positions (need {args.min_positions}); skipped")
            continue
        print(f"band {lo}-{hi}: scoring {len(jobs)} positions at depth {depth} on {args.workers} workers...")
        with Pool(args.workers) as pool:
            results = [r for r in pool.imap(_featurize, jobs, chunksize=32) if r is not None]
        X, sizes, chosen = [], [], []
        for rows, idx in results:
            X.extend(rows)
            sizes.append(len(rows))
            chosen.append(idx)
        cut = int(len(sizes) * 0.9)
        rows_cut = sum(sizes[:cut])
        w = fit_logit(X[:rows_cut], sizes[:cut], chosen[:cut], args.l2)
        train_m = evaluate_logit(w, X[:rows_cut], sizes[:cut], chosen[:cut])
        test_m = evaluate_logit(w, X[rows_cut:], sizes[cut:], chosen[cut:])
        print(f"  train {train_m}\n  held-out {test_m}")
        w = fit_logit(X, sizes, chosen, args.l2, w0=w)   # refit on everything for the saved model
        weights[centre] = [round(float(x), 5) for x in w]
        meta_bands[str(centre)] = {"range": [lo, hi], "positions": len(sizes), "held_out": test_m}
        for name, val in sorted(zip(FEATURE_NAMES, w), key=lambda t: -abs(t[1]))[:6]:
            print(f"    {name:>24s} {val:+.3f}")
    if not weights:
        sys.exit("No band had enough positions; nothing saved.")
    save_model(Path(args.out), weights, {"trained": datetime.now().isoformat(timespec="seconds"),
                                         "bands": meta_bands, "skip_plies": args.skip_plies,
                                         "min_clock": args.min_clock})
    print(f"Saved {len(weights)} band(s) to {args.out}")


# ---------------------------------------------------------------------------
# profile
# ---------------------------------------------------------------------------
CLAMP = 1000


def _white_cp(pov) -> int:
    return max(-CLAMP, min(CLAMP, pov.white().score(mate_score=10000)))


def game_evals(game, engine=None, depth: int = 12) -> list[int] | None:
    """White-POV centipawn eval of every position in the game (None if unavailable)."""
    evals, board = [], game.board()
    nodes = [game] + list(game.mainline())
    for node in nodes:
        pov = node.eval()
        if pov is None and engine is not None:
            pov = engine.analyse(node.board(), chess.engine.Limit(depth=depth))["score"]
        if pov is None:
            return None
        evals.append(_white_cp(pov))
    return evals


def move_phase(board: chess.Board) -> str:
    if board.fullmove_number <= 10:
        return "opening"
    material = sum(PIECE_VALUES[pt] * len(board.pieces(pt, c))
                   for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
                   for c in (chess.WHITE, chess.BLACK))
    return "middlegame" if material >= 3000 else "endgame"


def profile_games(games, min_elo=None, max_elo=None, name_re=None, assume_elo=None,
                  engine=None, depth: int = 12, skip_plies: int = 0) -> dict:
    stats = defaultdict(lambda: {"n": 0, "loss": 0.0, "inacc": 0, "mistake": 0, "blunder": 0})
    used = skipped = 0
    for game in games:
        sides = []
        for color in (chess.WHITE, chess.BLACK):
            elo = side_elo(game, color, assume_elo)
            name = game.headers.get("White" if color == chess.WHITE else "Black", "")
            ok_elo = elo is not None and (min_elo is None or elo >= min_elo) and (max_elo is None or elo <= max_elo)
            ok_name = bool(name_re and re.search(name_re, name))
            if (min_elo is None and max_elo is None and not name_re) or ok_name or (
                    (min_elo is not None or max_elo is not None) and ok_elo):
                sides.append(color)
        if not sides:
            continue
        evals = game_evals(game, engine, depth)
        if evals is None:
            skipped += 1
            continue
        used += 1
        board = game.board()
        for i, node in enumerate(game.mainline()):
            color = board.turn
            if color in sides and board.ply() >= skip_plies:
                before = evals[i] if color == chess.WHITE else -evals[i]
                after = evals[i + 1] if color == chess.WHITE else -evals[i + 1]
                if abs(before) < CLAMP:                    # ignore already-decided positions
                    loss = max(0, before - after)
                    for key in ("all", move_phase(board)):
                        s = stats[key]
                        s["n"] += 1
                        s["loss"] += loss
                        s["inacc"] += 50 <= loss < 100
                        s["mistake"] += 100 <= loss < 300
                        s["blunder"] += loss >= 300
            board.push(node.move)
    out = {"games_used": used, "games_skipped_no_eval": skipped, "phases": {}}
    for key, s in stats.items():
        n = s["n"]
        out["phases"][key] = {"moves": n, "acpl": round(s["loss"] / n, 1),
                              "inaccuracy_rate": round(s["inacc"] / n, 4),
                              "mistake_rate": round(s["mistake"] / n, 4),
                              "blunder_rate": round(s["blunder"] / n, 4)}
    return out


def cmd_profile(args) -> None:
    engine = None
    if args.stockfish:
        import chess.engine
        engine = chess.engine.SimpleEngine.popen_uci(args.stockfish)
    try:
        result = profile_games(iter_games(args.pgn), args.min_elo, args.max_elo, args.name,
                               args.assume_elo, engine, args.depth, args.skip_plies)
    finally:
        if engine:
            engine.quit()
    print(f"games used: {result['games_used']}   skipped (no evals): {result['games_skipped_no_eval']}")
    print(f"{'phase':<11}{'moves':>8}{'ACPL':>8}{'inacc':>9}{'mistake':>9}{'blunder':>9}")
    for phase in ("all", "opening", "middlegame", "endgame"):
        p = result["phases"].get(phase)
        if p:
            print(f"{phase:<11}{p['moves']:>8}{p['acpl']:>8}{p['inaccuracy_rate']:>9.1%}"
                  f"{p['mistake_rate']:>9.1%}{p['blunder_rate']:>9.1%}")
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("pgn", nargs="+")
        p.add_argument("--assume-elo", type=int, default=None,
                       help="rating to use for games with no Elo header (testing only)")

    b = sub.add_parser("book", help="mine an opening book")
    common(b)
    b.add_argument("--min-elo", type=int, default=900)
    b.add_argument("--max-elo", type=int, default=1500)
    b.add_argument("--plies", type=int, default=16)
    b.add_argument("--min-count", type=int, default=5, help="drop moves seen fewer times than this")
    b.add_argument("--min-share", type=float, default=0.03, help="drop moves played less often than this share")
    b.add_argument("--out", default=str(HUMAN_BOOK_PATH))
    b.set_defaults(fn=cmd_book)

    t = sub.add_parser("train", help="fit the human move-choice model")
    common(t)
    t.add_argument("--bands", nargs="+", default=["900-1100", "1100-1300", "1300-1500"])
    t.add_argument("--max-per-band", type=int, default=60000, help="positions per band (more = better, slower)")
    t.add_argument("--min-positions", type=int, default=2000)
    t.add_argument("--skip-plies", type=int, default=10, help="leave the opening to the book")
    t.add_argument("--min-clock", type=float, default=30.0,
                   help="skip moves played with fewer seconds left (time-trouble blunders); 0 = keep all")
    t.add_argument("--l2", type=float, default=1e-3)
    t.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    t.add_argument("--out", default=str(MODEL_PATH))
    t.set_defaults(fn=cmd_train)

    p = sub.add_parser("profile", help="inaccuracy / mistake / blunder rates")
    common(p)
    p.add_argument("--min-elo", type=int, default=None)
    p.add_argument("--max-elo", type=int, default=None)
    p.add_argument("--name", default=None, help="regex on player name instead of Elo (e.g. 'Bot@1000')")
    p.add_argument("--stockfish", default=None, help="analyse games that have no [%%eval] comments")
    p.add_argument("--depth", type=int, default=12)
    p.add_argument("--skip-plies", type=int, default=0)
    p.add_argument("--out", default=None)
    p.set_defaults(fn=cmd_profile)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
