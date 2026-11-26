# Opening repertoire

The bot plays only these openings, as deep as the files go, and never "forgets" theory
(`REPERTOIRE_FORGET = 0` in `patzer/config.py`):

| Bot plays | Opening | Against |
|---|---|---|
| White | Alien Gambit | 1.e4 c6 |
| White | Wayward Queen Attack | 1.e4 e5 |
| White | Alapin Sicilian | 1.e4 c5 |
| Black | Scandinavian Defense | 1.e4 |
| Black | King's Indian Defense | 1.d4 (any move order that reaches a KID setup) |

Files: `patzer/data/repertoire/*.pgn`. Out of theory (e.g. the opponent plays the French) the engine takes over,
guided by `patzer/engine/opening_sense.py`: develop minor pieces, take the centre, castle, don't walk the king,
don't bring the queen out early. These nudges only matter in the first ~15 moves and never outweigh winning material.
This also applies when Stockfish (1340+) is playing: it follows your theory first.

## Add or change theory (no code needed)
1. Export a Lichess study (or any PGN with variations) and save it in the folder as `white_<name>.pgn` or `black_<name>.pgn`
   (or add a `[Color "White"]` / `[Color "Black"]` header).
2. The first move at each branch is preferred (weight 4); other variations get weight 1.
   `!` (NAG $1) triples a move's weight; `?` or `??` bans it.
3. Check it: `python -m patzer.tools.repertoire_check` (reports illegal moves and coverage), or ask what the bot plays
   after some moves: `python -m patzer.tools.repertoire_check e4 c5`.

## Settings (`patzer/config.py`)
`REPERTOIRE_MODE` (False = old generic book), `REPERTOIRE_MAX_PLIES`, `REPERTOIRE_FORGET`,
`OPENING_SENSE` (0 = off), `OPENING_PREFER_SCALE` (smaller = stricter out of book).

## Not covered (the bot improvises with the opening principles)
French, Caro-Kann (other than the Alien Gambit line), Pirc, Alekhine, 1.d4 Trompowsky, 1.c4, 1.Nf3 ...
