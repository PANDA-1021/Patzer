"""Shortcut: `python calibrate.py ...` is the same as `python -m patzer.tools.calibrate ...`."""
from patzer.tools.calibrate import main

if __name__ == "__main__":  # required for multiprocessing on Windows
    main()
