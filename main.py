"""Launcher: `python main.py` (same as `python -m patzer`)."""
from patzer.gui.app import run

if __name__ == "__main__":
    run()
    if outcome.winner == self.human_color:
        text = "Checkmate - you win!"
    else:
        text = "Checkmate - the bot wins."
    if self.thinking:
        text = "Bot is thinking..."
    else:
        text = "Your move" + (" - check!" if b.is_check() else "")
    self.status_var.set(text)


def main() -> None:
    if sys.platform == "win32":  # crisp rendering on high-DPI Windows displays
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    ChessApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()