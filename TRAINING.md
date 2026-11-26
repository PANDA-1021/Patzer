# Training the bot on human games

1. **Get games.** Download a month from https://database.lichess.org, unpack with `zstd -d`.
   You only need a slice: `train` stops reading once every band has `--max-per-band` positions.
2. **Install training deps** (playing the app doesn't need them): `pip install -r requirements-train.txt`
3. **Opening book from real games** (seconds):
   `python -m patzer.tools.fit_human book lichess.pgn --min-elo 900 --max-elo 1500`
4. **Train the move-choice model** (~45 ms/position/core; 60k positions/band ≈ 45 min on one core):
   `python -m patzer.tools.fit_human train lichess.pgn --bands 900-1100 1100-1300 1300-1500`
   Writes `patzer/data/human_model.json`. Delete that file to go back to the hand-tuned `strength.py`.
5. **Check the blunder rate matches.**
   `python -m patzer.tools.fit_human profile lichess.pgn --min-elo 900 --max-elo 1100`   (humans, needs %eval games)
   `python -m patzer.tools.fit_human profile ladder_games.pgn --name "Bot@1000" --stockfish /path/to/sf` (bot)
   If the bot blunders less/more than the humans, lower/raise `HUMAN_MODEL_TEMPERATURE` in `config.py`.
6. **Re-run the ladder** (`python -m patzer.tools.ladder ...`): `strength_table.json` is stale once play changes.

Notes
* The built-in engine is only used below `STOCKFISH_MIN_ELO` (1320) in `backends/make_player`. Bands above that
  have no effect unless you change `uses_stockfish`.
* Lichess ratings are not chess.com or Stockfish-UCI_Elo ratings; use the ladder to see where the bot lands.
* The model chooses among moves the search can see (depth 2-3). It can't make the bot spot more than that.
