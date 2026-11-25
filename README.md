# Patzer

**A chess bot that plays like a human at the Elo you choose.**

Most chess engines are built to play the best move. Patzer is built to play a *believable* move: it looks a limited number of moves ahead, usually plays sensibly, and now and then makes the kind of small mistake a real club player makes. Pick a strength, play a game, and get an opponent that feels beatable instead of either hopeless or brutal.

> **Status: early development (v0.1).** The bot and GUI work as designed, but the Elo settings are still estimates and have not been calibrated against a reference engine yet. See [Roadmap](#roadmap).

---

## Features

- Desktop GUI built with `tkinter` and `python-chess`; no browser or server needed
- Drag-and-drop or click-to-move, with legal-move hints, last-move and check highlighting
- Play as **White or Black** with one click; the board flips automatically
- Smooth play: the bot thinks in a background thread, pieces slide into place, and the board resizes with the window
- Promotion picker, move list, undo, flip board
- Elo-based strength model (currently fixed at 1000; the dropdown is built and ready to unlock)
- Calibration tool that plays the bot against Stockfish to measure its real strength

## Quick start

Requires Python 3.10 or newer. `tkinter` ships with most Python installs (on some Linux distros: `sudo apt install python3-tk`).

```bash
git clone <(https://github.com/PANDA-1021/Patzer/)> patzer
cd patzer
pip install -r requirements.txt
python main.py
```

### Controls

| Action | How |
|---|---|
| Move a piece | Drag it, or click it and then click the destination |
| Switch sides | "You play as" selector (starts a new game) |
| New game | Button or `N` |
| Undo | Button or `U` |
| Flip board | Button or `F` |

## How the bot plays

The bot does a shallow search over a simple evaluation (material plus small positional bonuses), then chooses its move on purpose imperfectly. Strength is controlled by a few settings derived from a target Elo (see `elo_params` in `main.py`):

| Setting | What it does |
|---|---|
| **Search depth** | How many moves ahead it sees. Missed forks, pins and traps come from this limit. |
| **Small mistakes** | A modest chance of a slightly worse move, costing at most about a pawn. |
| **Piece blunders** | A very small chance (`PIECE_BLUNDER_RATE`) of giving up a piece in one move. Never hangs a queen or allows mate. |
| **Tie window** | Normal moves are chosen among near-equal best moves, so real material gains are always taken. |

The Elo selector is locked at 1000 for now. To unlock it, set `ELO_SELECTOR_ENABLED = True` in `main.py`.

## Calibration

The mapping from setting to real strength is currently a hand-tuned estimate. `calibrate.py` measures it by playing many games against Stockfish (limited with `UCI_Elo`) or against another bot setting, alternating colors on identical random openings, and converting the score into an Elo estimate with a 95% confidence interval.

```bash
# quick smoke test
python calibrate.py --stockfish "path/to/stockfish" --bot-elo 1340 --games 2 --workers 1

# a real sweep, saving games for review
python calibrate.py --stockfish "path/to/stockfish" --bot-elo 1340 1500 1700 --games 40 --pgn games.pgn

# measure a low setting against an already-calibrated bot anchor
python calibrate.py --bot-elo 1000 --opp-bot 1340 --opp-rating 1340 --games 40
```

Results are appended to `calibration_results.csv`. Install Stockfish from [stockfishchess.org](https://stockfishchess.org/download/) (or `brew install stockfish` / `sudo apt install stockfish`).

**Caveats**

- Stockfish's `UCI_Elo` floor is 1320, so low settings must be measured against a bot anchor rather than Stockfish directly. Results near 0% or 100% are flagged as unreliable.
- Stockfish's Elo labels assume long time controls; at short move times it plays weaker than labeled. Treat results as a consistent relative scale, not an exact Lichess or chess.com rating.

## Project layout

```
main.py             GUI app and the built-in engine
calibrate.py        Strength measurement against Stockfish or another bot setting
requirements.txt    Python dependencies
```

A planned restructure will split the engine, backends, GUI and tools into separate modules.

## Roadmap

- [x] Playable GUI with side switching and smooth animation
- [x] Elo-based strength model with human-style mistakes
- [x] Calibration harness
- [ ] Automated tests for the bot's behavior
- [ ] Restructure into modules with swappable engine backends
- [ ] Calibrate against Stockfish and replace the estimated Elo formulas
- [ ] Stronger engine: quiescence search, transposition table, better evaluation
- [ ] Stockfish backend for the high-Elo range
- [ ] Unlock the Elo dropdown (1340 and up in steps of 50)
- [ ] Optional: Maia neural-net backend for realistic 1100 to 1900 play
- [ ] Game clocks, resign and draw offers, PGN save and load, game review
- [ ] Windows `.exe` release

## Known limitations

- Elo settings are not yet calibrated, so "1000" is approximate.
- The built-in engine is pure Python; settings above about 1900 search deeper and will feel slow.
- No clocks, opening book, or endgame tablebases yet.

## Built with

[python-chess](https://python-chess.readthedocs.io/) for rules and move generation, `tkinter` for the interface, and [Stockfish](https://stockfishchess.org/) as the reference opponent for calibration.

## License

Not yet chosen.
