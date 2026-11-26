"""User-facing settings. Edit these to change the app's behaviour."""

DEFAULT_ELO = 1000

# Dropdown choices. 1000 uses the built-in human-like engine; 1340 and up use Stockfish
# (limited with its UCI_Elo option, which starts at 1320).
ELO_OPTIONS = [1000, 1340] + list(range(1400, 2850, 50))

# Set to False to lock the Elo dropdown at DEFAULT_ELO.
ELO_SELECTOR_ENABLED = True

# Stockfish range and thinking time per move (seconds). Stockfish's Elo labels assume
# long time controls, so very short move times make it play weaker than labelled.
STOCKFISH_MIN_ELO = 1320
STOCKFISH_MAX_ELO = 3190
STOCKFISH_MOVETIME = 1.0

MIN_THINK_SECONDS = 0.45   # so instant replies don't feel jarring
ANIMATION_FRAME_MS = 15
ANIMATION_FRAMES = 12

# Human-like move choice learned from real games (see patzer/tools/fit_human.py).
# Used only if patzer/data/human_model.json exists; otherwise strength.py's hand-tuned rules apply.
HUMAN_MODEL_ENABLED = True
# 1.0 = play exactly like the training data. Above 1 = more mistakes, below 1 = fewer.
# Tune this after training so the bot's measured blunder rate matches the humans' (see README notes).
HUMAN_MODEL_TEMPERATURE = 1.0

# --- Opening repertoire (patzer/data/repertoire/*.pgn; see patzer/engine/repertoire.py) ---
# True: the bot plays ONLY the openings in that folder, as deep as the files go, and never
# "forgets" a theory move. Out of theory it uses the engine plus opening_sense.py.
# False: the old generic book (engine/book.py) is used instead.
REPERTOIRE_MODE = True
REPERTOIRE_MAX_PLIES = 60     # stop following theory after this many half-moves
REPERTOIRE_FORGET = 0.0       # chance per move of skipping a theory move (0 = never)

# Out-of-book guidance: development, centre control, king safety (engine/opening_sense.py).
# 1.0 = normal, 0 = off, 2.0 = twice as strong.
OPENING_SENSE = 1.0
# Out of book in the opening, pick among near-equal moves favouring the sounder ones: a move this many
# centipawns worse is about 2.7x less likely. Smaller = stricter. Ignored after the opening.
OPENING_PREFER_SCALE = 30.0
