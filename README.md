# Patzer

**A chess bot that plays like a human at the Elo you choose.**

Most chess engines are built to play the best move. Patzer is built to play a *believable* move: it follows an opening repertoire, looks a limited number of moves ahead, usually plays sensibly, and now and then makes the kind of small mistake a real club player makes. Pick a strength, play a game, and get an opponent that feels beatable instead of either hopeless or brutal.

> **Status: early development.** The bot, GUI, test suite and calibration tools work, but the Elo labels have not yet been calibrated against the current engine. See the [Roadmap](#roadmap).

---

## Features

- Desktop GUI built with `tkinter` and `python-chess`; no browser or server needed
- Drag-and-drop or click-to-move, with legal-move hints, last-move and check highlighting
- Play as **White or Black** with one click; the board flips automatically
- Smooth play: the bot thinks in a background thread, pieces slide into place, and the board resizes with the window
- Promotion picker, move list, undo, flip board
- Small opening repertoire, so games start like a club player's
- Elo dropdown: 1000 is played by the built-in human-like engine, 1340 to 2800 by Stockfish (limited with `UCI_Elo`)
- Calibration tools that measure the bot's real strength against Stockfish and against itself

## Quick start

Requires Python 3.10 or newer. `tkinter` ships with most Python installs (on some Linux distros: `sudo apt install python3-tk`).

```bash
git clone https://github.com/PANDA-1021/Patzer.git
cd Patzer
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

1. **Opening book:** it plays a weighted repertoire for the first several moves, and occasionally "forgets" it (more often at lower Elo).
2. **Search:** an alpha-beta search a few moves deep with quiescence, so it resolves captures properly instead of stopping mid-exchange.
3. **Evaluation:** material plus small positional terms (centre control, development, castling, king hunting in endgames).
4. **Deliberate imperfection:** strength settings derived from the target Elo (see `strength_params` in `patzer/engine/strength.py`):

| Setting | What it does |
|---|---|
| **Search depth** | How many moves ahead it sees. Missed forks, pins and traps come from this limit. |
| **Small mistakes** | A modest chance of a slightly worse move, costing at most about a pawn. |
| **Piece blunders** | A very small chance (`PIECE_BLUNDER_RATE`) of giving up a piece in one move. Never hangs a queen or allows mate. |
| **Tie window** | Normal moves are chosen among near-equal best moves, so real material gains are always taken. |

### Choosing a strength

| Dropdown value | Played by |
|---|---|
| 1000 | The built-in engine described above (the human-like bot) |
| 1340 to 2800 | Stockfish, limited with its `UCI_Elo` option |

The first time you pick a Stockfish strength, Patzer looks for Stockfish in `$STOCKFISH_PATH`, then in your saved settings, then on your `PATH`. If it can't find it, it asks you to locate the program and remembers the answer in `~/.patzer/settings.json` (outside the project, so it never reaches git). To lock the dropdown, set `ELO_SELECTOR_ENABLED = False` in `patzer/config.py`; the dropdown choices and Stockfish thinking time (`STOCKFISH_MOVETIME`) are there too.

## Calibration

The mapping from setting to real strength is still a hand-tuned estimate. Two tools measure it:

**`ladder`: measure every setting in one run (recommended).** Neighbouring settings play each other and Stockfish; one rating per setting is fitted by maximum likelihood. Set the `STOCKFISH_PATH` environment variable once (or pass `--stockfish`).

```bash
# quick check, bot vs bot only, no Stockfish needed
python -m patzer.tools.ladder --settings 400 1000 --games 4 --workers 1 --max-plies 100

# the real run, anchored to Stockfish at 1320
python -m patzer.tools.ladder --settings 400 700 1000 1340 1500 1700 --games 40 \
    --vs-stockfish 1340 1500 --sf-elo 1320 --pgn ladder_games.pgn
```

It prints a table and writes `strength_table.json` (latest) and `ladder_results.csv` (history). Games that reach `--max-plies` are adjudicated by material (decisive if one side is up 3 or more pawns, otherwise a draw), so unconverted wins still count.

**`calibrate`: one setting against Stockfish or another setting.**

```bash
python -m patzer.tools.calibrate --bot-elo 1340 1500 --games 40 --pgn games.pgn
python -m patzer.tools.calibrate --bot-elo 1000 --opp-bot 1340 --opp-rating 1340 --games 40
```

(`python calibrate.py ...` still works as a shortcut.) Install Stockfish from [stockfishchess.org](https://stockfishchess.org/download/) (or `brew install stockfish` / `sudo apt install stockfish`).

**Caveats**

- Stockfish's `UCI_Elo` floor is 1320, so low settings are measured through chains of bot-vs-bot games. Results near 0% or 100% are flagged as weak evidence.
- Stockfish's Elo labels assume long time controls; at short move times it plays weaker than labelled. Treat results as a consistent relative scale, not an exact Lichess or chess.com rating.

## Testing

```bash
pytest
```

The suite checks the bot's behaviour on concrete positions (takes a free piece, plays mate in one, never hangs its queen, handles promotion, castling and en passant), the opening book, the evaluation function, and the rating maths.

## Project layout

```
main.py             Launcher (same as `python -m patzer`)
calibrate.py        Shortcut to patzer/tools/calibrate.py
patzer/engine/      Evaluation, search (with quiescence), opening book, strength settings
patzer/backends/    Move providers behind one interface: built-in engine and Stockfish
patzer/gui/         The tkinter board and app
patzer/config.py    Default Elo, dropdown options, Stockfish range and thinking time
patzer/settings.py  Per-user settings (Stockfish location), stored in your home folder
patzer/tools/       Calibration: calibrate.py (one setting), ladder.py (all settings), stats.py
tests/              pytest checks
requirements.txt    Python dependencies
```

## Roadmap

- [x] Playable GUI with side switching and smooth animation
- [x] Elo-based strength model with human-style mistakes
- [x] Calibration tools (single setting and full ladder)
- [x] Automated tests
- [x] Modular layout with swappable engine backends
- [x] Quiescence search, better evaluation, opening book
- [ ] Calibrate against Stockfish and replace the estimated Elo formulas
- [x] Stockfish backend and unlocked Elo dropdown (1000, then 1340 and up in steps of 50)
- [ ] Transposition table and further speed-ups
- [ ] Optional: Maia neural-net backend for realistic 1100 to 1900 play
- [ ] Game clocks, resign and draw offers, PGN save and load, game review
- [ ] Windows `.exe` release

## Known limitations

- The built-in engine's settings between 400 and 1340 currently play at almost the same strength (about 1100 to 1150 on the Stockfish scale used for calibration); only the 1500 setting (deeper search) is clearly stronger. Until weaker profiles are added, treat the built-in engine as one level.
- Stockfish's Elo labels assume long time controls, so at the default 1 second per move it may play somewhat below its label.
- The built-in engine is pure Python; the deepest settings (1900 and up) are slow in the middlegame.
- No clocks or endgame tablebases yet.

## Built with

[python-chess](https://python-chess.readthedocs.io/) for rules and move generation, `tkinter` for the interface, and [Stockfish](https://stockfishchess.org/) as the reference opponent for calibration.

## License

Not yet chosen.
