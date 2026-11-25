"""User-facing settings. Edit these to change the app's behaviour."""

DEFAULT_ELO = 1000

# Dropdown choices: 1340, then 1400 up to 2200 in steps of 50.
ELO_OPTIONS = [1340] + list(range(1400, 2250, 50))

# Flip to True to unlock the Elo dropdown in the GUI.
ELO_SELECTOR_ENABLED = False

MIN_THINK_SECONDS = 0.45   # so instant replies don't feel jarring
ANIMATION_FRAME_MS = 15
ANIMATION_FRAMES = 12
