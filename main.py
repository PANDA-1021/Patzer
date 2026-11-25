"""
Chess Bot - play against a bot tuned to a target Elo.

Setup:  pip install -r requirements.txt     (tkinter ships with most Python installs)
Run:    python main.py

Controls
  * Drag a piece, or click a piece and then click its destination.
  * "You play as" switches sides (starts a new game, board flips automatically).
  * Keys: N = new game, U = undo, F = flip board.

Elo
  The bot is fixed at DEFAULT_ELO for now. The dropdown is already wired up:
  set ELO_SELECTOR_ENABLED = True to unlock it.

Strength is controlled by knobs derived from the target Elo (see elo_params):
  1. search depth        (how far ahead it sees)
  2. small mistakes      (rare, cost at most about a pawn)
  3. piece blunders      (very rare, PIECE_BLUNDER_RATE; never hangs a queen or allows mate)
These mappings are estimates - calibrate them against Stockfish (UCI_Elo).
"""
from __future__ import annotations

import math
import queue
import random
import sys
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk

import chess

# =============================================================================
# Configuration
# =============================================================================
DEFAULT_ELO = 1000
# Dropdown choices: 1340, then 1400 up to 2200 in steps of 50. (Stockfish's
# UCI_Elo floor is 1320, so this range lines up with it for future matches.)
ELO_OPTIONS = [1340] + list(range(1400, 2250, 50))
ELO_SELECTOR_ENABLED = False      # flip to True to unlock the Elo dropdown

# Chance (at 400 Elo, shrinking to 0 at 2200) that a bot move gives up a piece
# in one move. Kept very low on purpose: at 1000 Elo it is about 0.3% per move.
PIECE_BLUNDER_RATE = 0.005
PIECE_LOSS_RANGE = (250, 700)     # a piece-losing blunder costs 250-700 centipawns

MIN_THINK_SECONDS = 0.45          # so instant replies don't feel jarring
ANIMATION_FRAME_MS = 15
ANIMATION_FRAMES = 12

# Board colours
LIGHT, DARK = "#f0d9b5", "#b58863"
LAST_LIGHT, LAST_DARK = "#e6e07a", "#c4b43c"
SEL_LIGHT, SEL_DARK = "#f6f669", "#baca2b"
CHECK_COLOR = "#e8665f"
HINT_COLOR = "#6b8e4e"
CANVAS_BG = "#312e2b"

GLYPHS = {
    chess.KING: "\u265a", chess.QUEEN: "\u265b", chess.ROOK: "\u265c",
    chess.BISHOP: "\u265d", chess.KNIGHT: "\u265e",
    # U+FE0E forces text (not emoji) rendering of the pawn on macOS
    chess.PAWN: "\u265f" + ("\ufe0e" if sys.platform == "darwin" else ""),
}

# =============================================================================
# Engine
# =============================================================================
MATE = 100_000
PIECE_VALUES = {
    chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
    chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 0,
}


def _center_dist(sq: int) -> float:
    return max(abs(chess.square_file(sq) - 3.5), abs(chess.square_rank(sq) - 3.5))


def _mop_up(attacker_king: int, defender_king: int) -> float:
    """Endgame bonus: drive the defending king to the edge, bring own king close."""
    return 10 * _center_dist(defender_king) + 4 * (7 - chess.square_distance(attacker_king, defender_king))


def evaluate(board: chess.Board) -> float:
    """Static score in centipawns from the side-to-move's perspective."""
    score = 0.0
    piece_material = 0
    wk = bk = 0
    for sq, piece in board.piece_map().items():
        pt = piece.piece_type
        value = PIECE_VALUES[pt]
        centrality = 3.5 - _center_dist(sq)  # 0 (edge) .. 3 (center)
        if pt in (chess.KNIGHT, chess.BISHOP):
            value += centrality * 8
        elif pt == chess.PAWN:
            rank = chess.square_rank(sq)
            progress = rank if piece.color == chess.WHITE else 7 - rank
            value += progress * 6 + centrality * 2
        elif pt == chess.KING:
            if piece.color == chess.WHITE:
                wk = sq
            else:
                bk = sq
        if pt not in (chess.PAWN, chess.KING):
            piece_material += PIECE_VALUES[pt]
        score += value if piece.color == chess.WHITE else -value

    if piece_material <= 1400:  # endgame: help the stronger side actually finish
        if score > 150:
            score += _mop_up(wk, bk)
        elif score < -150:
            score -= _mop_up(bk, wk)

    return score if board.turn == chess.WHITE else -score


def order_moves(board: chess.Board) -> list[chess.Move]:
    def key(m: chess.Move) -> int:
        k = 800 if m.promotion else 0
        if board.is_capture(m):
            victim = board.piece_type_at(m.to_square) or chess.PAWN  # en passant
            attacker = board.piece_type_at(m.from_square)
            k += 10 * PIECE_VALUES[victim] - PIECE_VALUES[attacker]
        return k
    return sorted(board.legal_moves, key=key, reverse=True)


def negamax(board: chess.Board, depth: int, alpha: float, beta: float, ply: int) -> float:
    if depth == 0:
        if board.is_check() and not any(board.legal_moves):
            return -MATE + ply
        return evaluate(board)
    moves = order_moves(board)
    if not moves:
        return -MATE + ply if board.is_check() else 0
    if board.is_insufficient_material():
        return 0
    best = -math.inf
    for move in moves:
        board.push(move)
        score = -negamax(board, depth - 1, -beta, -alpha, ply + 1)
        board.pop()
        if score > best:
            best = score
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
    return best


def elo_params(elo: int) -> tuple[int, float, float, float, float]:
    """Map a target Elo to (depth, blunder_prob, miss_prob, tie_window, miss_window).

    depth         plies the bot looks ahead (always >= 2, so it sees any reply that
                  captures a piece it just left hanging)
    blunder_prob  rare chance of a one-move blunder that gives up a piece
    miss_prob     chance of a soft mistake: a small inaccuracy that costs at most
                  about a pawn (passing up a pawn win, leaving a pawn loose, ...)
    tie_window    normal moves are picked among moves within this many centipawns
                  of the best one, so real material gains are always taken
    miss_window   soft mistakes are picked within this many centipawns of the best

    Missed tactics (forks, pins, traps) come from the limited search depth.
    """
    elo = max(400, min(2200, elo))
    if elo < 1400:
        depth = 2
    elif elo < 1900:
        depth = 3
    else:
        depth = 4
    t = (elo - 400) / 1800  # 0..1
    blunder_prob = PIECE_BLUNDER_RATE * (1 - t) ** 1.2
    miss_prob = 0.25 * (1 - t) ** 1.2
    tie_window = 15 + 45 * (1 - t)
    miss_window = 100 + 100 * (1 - t)
    return depth, blunder_prob, miss_prob, tie_window, miss_window


class EloBot:
    def __init__(self, elo: int = DEFAULT_ELO):
        self.set_elo(elo)

    def set_elo(self, elo: int) -> None:
        self.elo = elo
        (self.depth, self.blunder_prob, self.miss_prob,
         self.tie_window, self.miss_window) = elo_params(elo)

    def pick(self, scored: list) -> object:
        """Choose a move from [(move, score), ...] according to this bot's Elo."""
        best = max(s for _, s in scored)
        roll = random.random()
        if roll < self.blunder_prob:  # rare: gives up a piece
            lo, hi = PIECE_LOSS_RANGE
            pool = [m for m, s in scored if best - hi <= s <= best - lo]
            if pool:
                return random.choice(pool)
        if roll < self.blunder_prob + self.miss_prob:  # small inaccuracy
            pool = [m for m, s in scored if s >= best - self.miss_window]
        else:  # best move, or a near-equal alternative
            pool = [m for m, s in scored if s >= best - self.tie_window]
        return random.choice(pool)

    def choose_move(self, board: chess.Board) -> chess.Move:
        board = board.copy()  # never touch the caller's board from a worker thread
        moves = list(board.legal_moves)
        if len(moves) == 1:
            return moves[0]
        scored = []
        for move in moves:
            board.push(move)
            s = -negamax(board, self.depth - 1, -math.inf, math.inf, 1)
            board.pop()
            scored.append((move, max(-1500.0, min(1500.0, s))))  # clamp mate scores
        return self.pick(scored)


# =============================================================================
# GUI
# =============================================================================
def pick_font(root: tk.Misc) -> str:
    available = set(tkfont.families(root))
    for name in ("Segoe UI Symbol", "Apple Symbols", "DejaVu Sans",
                 "Noto Sans Symbols2", "FreeSerif", "Arial Unicode MS"):
        if name in available:
            return name
    return "TkDefaultFont"


def is_light_square(f: int, r: int) -> bool:
    return (f + r) % 2 == 1


class ChessApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Chess Bot")
        root.minsize(760, 560)

        self.bot = EloBot(DEFAULT_ELO)
        self.board = chess.Board()
        self.human_color = chess.WHITE
        self.flipped = False

        self.sq = 80
        self.ox = self.oy = 0
        self.sel: int | None = None
        self.targets: dict[int, list[chess.Move]] = {}
        self.last_move: chess.Move | None = None
        self.san_list: list[str] = []

        self.thinking = False
        self.animating = False
        self.anim_hide: int | None = None
        self.game_id = 0

        self.drag_from: int | None = None
        self.drag_active = False
        self.drag_start = (0, 0)
        self.drag_pos = (0, 0)

        self.results: queue.Queue = queue.Queue()
        self._poll_job = None
        self.font_family = pick_font(root)

        self._build_ui()
        root.update_idletasks()
        self.new_game()

    # ------------------------------------------------------------------ UI --
    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(main, width=640, height=640, bg=CANVAS_BG, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.draw())
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_motion)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

        panel = ttk.Frame(main, padding=(14, 0, 0, 0))
        panel.pack(side="right", fill="y")

        self.status_var = tk.StringVar()
        ttk.Label(panel, textvariable=self.status_var, font=("TkDefaultFont", 13, "bold"),
                  wraplength=230, justify="left").pack(anchor="w", pady=(0, 12))

        side_box = ttk.LabelFrame(panel, text="You play as", padding=8)
        side_box.pack(fill="x", pady=(0, 10))
        self.side_var = tk.StringVar(value="white")
        ttk.Radiobutton(side_box, text="White", value="white", variable=self.side_var,
                        command=self.on_side_change).pack(side="left", padx=(0, 16))
        ttk.Radiobutton(side_box, text="Black", value="black", variable=self.side_var,
                        command=self.on_side_change).pack(side="left")

        elo_box = ttk.LabelFrame(panel, text="Bot strength (Elo)", padding=8)
        elo_box.pack(fill="x", pady=(0, 10))
        self.elo_var = tk.StringVar(value=str(DEFAULT_ELO))
        self.elo_combo = ttk.Combobox(
            elo_box, textvariable=self.elo_var, values=[str(e) for e in ELO_OPTIONS],
            width=10, state="readonly" if ELO_SELECTOR_ENABLED else "disabled")
        self.elo_combo.pack(anchor="w")
        self.elo_combo.bind("<<ComboboxSelected>>", self.on_elo_change)
        if not ELO_SELECTOR_ENABLED:
            ttk.Label(elo_box, text="Locked for now", foreground="#888").pack(anchor="w", pady=(4, 0))

        btns = ttk.Frame(panel)
        btns.pack(fill="x", pady=(0, 10))
        ttk.Button(btns, text="New game", command=self.on_new_game_click).pack(fill="x", pady=2)
        ttk.Button(btns, text="Undo move", command=self.undo).pack(fill="x", pady=2)
        ttk.Button(btns, text="Flip board", command=self.flip).pack(fill="x", pady=2)

        ttk.Label(panel, text="Moves").pack(anchor="w")
        text_frame = ttk.Frame(panel)
        text_frame.pack(fill="both", expand=True)
        self.moves_text = tk.Text(text_frame, width=24, height=14, state="disabled",
                                  font=("Courier", 11), relief="flat", borderwidth=1)
        scroll = ttk.Scrollbar(text_frame, command=self.moves_text.yview)
        self.moves_text.config(yscrollcommand=scroll.set)
        self.moves_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.root.bind("<Key-n>", lambda e: self.on_new_game_click())
        self.root.bind("<Key-u>", lambda e: self.undo())
        self.root.bind("<Key-f>", lambda e: self.flip())

    # ------------------------------------------------------------ geometry --
    def _layout(self) -> None:
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        self.sq = max(24, min(w, h) // 8)
        self.ox = (w - 8 * self.sq) // 2
        self.oy = (h - 8 * self.sq) // 2

    def sq_origin(self, square: int) -> tuple[int, int]:
        f, r = chess.square_file(square), chess.square_rank(square)
        col = 7 - f if self.flipped else f
        row = r if self.flipped else 7 - r
        return self.ox + col * self.sq, self.oy + row * self.sq

    def sq_center(self, square: int) -> tuple[float, float]:
        x, y = self.sq_origin(square)
        return x + self.sq / 2, y + self.sq / 2

    def xy_to_sq(self, x: int, y: int) -> int | None:
        col, row = (x - self.ox) // self.sq, (y - self.oy) // self.sq
        if not (0 <= col < 8 and 0 <= row < 8):
            return None
        f = 7 - col if self.flipped else col
        r = row if self.flipped else 7 - row
        return chess.square(f, r)

    # ------------------------------------------------------------- drawing --
    def draw_piece(self, piece: chess.Piece, cx: float, cy: float, tag: str) -> None:
        glyph = GLYPHS[piece.piece_type]
        fnt = (self.font_family, -int(self.sq * 0.72))
        if piece.color == chess.WHITE:
            fill, outline = "#ffffff", "#1b1b1b"
        else:
            fill, outline = "#141414", "#cfcfcf"
        for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            self.canvas.create_text(cx + dx, cy + dy, text=glyph, font=fnt, fill=outline, tags=(tag,))
        self.canvas.create_text(cx, cy, text=glyph, font=fnt, fill=fill, tags=(tag,))

    def draw(self) -> None:
        c = self.canvas
        c.delete("all")
        self._layout()
        sq = self.sq
        check_sq = self.board.king(self.board.turn) if self.board.is_check() else None
        last = {self.last_move.from_square, self.last_move.to_square} if self.last_move else set()

        for s in chess.SQUARES:
            x, y = self.sq_origin(s)
            light = is_light_square(chess.square_file(s), chess.square_rank(s))
            color = LIGHT if light else DARK
            if s in last:
                color = LAST_LIGHT if light else LAST_DARK
            if s == self.sel:
                color = SEL_LIGHT if light else SEL_DARK
            if s == check_sq:
                color = CHECK_COLOR
            c.create_rectangle(x, y, x + sq, y + sq, fill=color, outline="")

        small = ("Helvetica", -max(9, sq // 6), "bold")
        for col in range(8):
            f = 7 - col if self.flipped else col
            r = 0 if not self.flipped else 7
            color = DARK if is_light_square(f, r) else LIGHT
            c.create_text(self.ox + col * sq + sq - 4, self.oy + 8 * sq - 3,
                          text="abcdefgh"[f], anchor="se", fill=color, font=small)
        for row in range(8):
            r = row if self.flipped else 7 - row
            f = 7 if self.flipped else 0
            color = DARK if is_light_square(f, r) else LIGHT
            c.create_text(self.ox + 4, self.oy + row * sq + 2,
                          text=str(r + 1), anchor="nw", fill=color, font=small)

        # legal-move hints
        for t, moves in self.targets.items():
            cx, cy = self.sq_center(t)
            if self.board.is_capture(moves[0]):
                rr = sq * 0.45
                c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, outline=HINT_COLOR, width=max(3, sq // 14))
            else:
                rr = sq * 0.15
                c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, fill=HINT_COLOR, outline="")

        for s, piece in self.board.piece_map().items():
            if s == self.anim_hide or (self.drag_active and s == self.drag_from):
                continue
            cx, cy = self.sq_center(s)
            self.draw_piece(piece, cx, cy, "piece")

    # --------------------------------------------------------------- input --
    def can_human_move(self) -> bool:
        return (not self.thinking and not self.animating
                and self.board.turn == self.human_color
                and not self.board.is_game_over(claim_draw=True))

    def select(self, square: int) -> None:
        self.sel = square
        self.targets = {}
        for m in self.board.legal_moves:
            if m.from_square == square:
                self.targets.setdefault(m.to_square, []).append(m)

    def on_press(self, e: tk.Event) -> None:
        if not self.can_human_move():
            return
        s = self.xy_to_sq(e.x, e.y)
        if s is None:
            return
        if self.sel is not None and s in self.targets:  # click-click move
            self.try_move(s, animate=True)
            return
        piece = self.board.piece_at(s)
        if piece and piece.color == self.human_color:
            self.select(s)
            self.drag_from = s
            self.drag_active = False
            self.drag_start = self.drag_pos = (e.x, e.y)
        else:
            self.sel, self.targets = None, {}
        self.draw()

    def on_motion(self, e: tk.Event) -> None:
        if self.drag_from is None:
            return
        if not self.drag_active:
            if abs(e.x - self.drag_start[0]) + abs(e.y - self.drag_start[1]) < 5:
                return
            self.drag_active = True
            self.draw()  # hides the origin piece
            piece = self.board.piece_at(self.drag_from)
            if piece:
                self.draw_piece(piece, e.x, e.y, "drag")
            self.drag_pos = (e.x, e.y)
            return
        self.canvas.move("drag", e.x - self.drag_pos[0], e.y - self.drag_pos[1])
        self.drag_pos = (e.x, e.y)

    def on_release(self, e: tk.Event) -> None:
        if self.drag_from is None:
            return
        was_drag, src = self.drag_active, self.drag_from
        self.drag_from, self.drag_active = None, False
        if not was_drag:
            return  # plain click: selection stays so a second click can move
        self.canvas.delete("drag")
        s = self.xy_to_sq(e.x, e.y)
        if s is not None and s != src and s in self.targets:
            self.try_move(s, animate=False)
        else:
            self.draw()

    def try_move(self, dst: int, animate: bool) -> None:
        moves = self.targets.get(dst, [])
        if not moves:
            return
        if len(moves) > 1:  # promotion
            piece_type = self.ask_promotion()
            move = next((m for m in moves if m.promotion == piece_type), moves[0])
        else:
            move = moves[0]
        self.play_move(move, animate)

    def ask_promotion(self) -> int:
        top = tk.Toplevel(self.root)
        top.title("Promote to")
        top.transient(self.root)
        top.resizable(False, False)
        choice = {"piece": chess.QUEEN}

        def pick(p: int) -> None:
            choice["piece"] = p
            top.destroy()

        glyph_font = (self.font_family, 34)
        for p in (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT):
            tk.Button(top, text=GLYPHS[p], font=glyph_font, width=2,
                      command=lambda p=p: pick(p)).pack(side="left", padx=4, pady=6)
        top.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - top.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - top.winfo_height()) // 2
        top.geometry(f"+{x}+{y}")
        top.wait_visibility()
        top.grab_set()
        self.root.wait_window(top)
        return choice["piece"]

    # --------------------------------------------------------- move playing --
    def play_move(self, move: chess.Move, animate: bool) -> None:
        gid = self.game_id
        if animate:
            self.sel, self.targets = None, {}
            self.animate_move(move, lambda: self.commit_move(move, gid))
        else:
            self.commit_move(move, gid)

    def animate_move(self, move: chess.Move, done) -> None:
        gid = self.game_id
        piece = self.board.piece_at(move.from_square)
        self.animating = True
        self.anim_hide = move.from_square
        self.draw()
        x0, y0 = self.sq_center(move.from_square)
        x1, y1 = self.sq_center(move.to_square)
        self.draw_piece(piece, x0, y0, "anim")
        state = {"i": 0, "x": x0, "y": y0}

        def step() -> None:
            if gid != self.game_id:
                return
            state["i"] += 1
            t = state["i"] / ANIMATION_FRAMES
            e = t * t * (3 - 2 * t)  # smoothstep easing
            nx, ny = x0 + (x1 - x0) * e, y0 + (y1 - y0) * e
            self.canvas.move("anim", nx - state["x"], ny - state["y"])
            state["x"], state["y"] = nx, ny
            if state["i"] >= ANIMATION_FRAMES:
                self.canvas.delete("anim")
                done()
            else:
                self.root.after(ANIMATION_FRAME_MS, step)

        self.root.after(ANIMATION_FRAME_MS, step)

    def commit_move(self, move: chess.Move, gid: int) -> None:
        if gid != self.game_id:
            return
        san = self.board.san(move)
        self.board.push(move)
        self.animating = False
        self.anim_hide = None
        self.sel, self.targets = None, {}
        self.last_move = move
        self.san_list.append(san)
        self.refresh_moves()
        self.draw()
        self.after_move()

    def after_move(self) -> None:
        if self.board.is_game_over(claim_draw=True):
            self.update_status()
            return
        if self.board.turn != self.human_color:
            self.start_bot()
        else:
            self.update_status()

    # ----------------------------------------------------------------- bot --
    def start_bot(self) -> None:
        self.thinking = True
        self.update_status()
        gid, snapshot, started = self.game_id, self.board.copy(), time.time()

        def work() -> None:
            try:
                move = self.bot.choose_move(snapshot)
            except Exception as exc:  # never leave the UI stuck on "thinking"
                print("Bot error:", exc, file=sys.stderr)
                move = random.choice(list(snapshot.legal_moves))
            self.results.put((gid, move, started))

        threading.Thread(target=work, daemon=True).start()
        self._poll_job = self.root.after(30, self.poll_bot)

    def poll_bot(self) -> None:
        self._poll_job = None
        while True:
            try:
                gid, move, started = self.results.get_nowait()
            except queue.Empty:
                self._poll_job = self.root.after(30, self.poll_bot)
                return
            if gid != self.game_id:
                continue  # stale result from a previous game
            wait_ms = max(0, int((MIN_THINK_SECONDS - (time.time() - started)) * 1000))
            self.root.after(wait_ms, lambda: self.play_bot_move(move, gid))
            return

    def play_bot_move(self, move: chess.Move, gid: int) -> None:
        if gid != self.game_id:
            return
        self.thinking = False
        self.update_status()
        self.animate_move(move, lambda: self.commit_move(move, gid))

    # ------------------------------------------------------------- actions --
    def game_in_progress(self) -> bool:
        return bool(self.board.move_stack) and not self.board.is_game_over(claim_draw=True)

    def new_game(self) -> None:
        self.game_id += 1
        if self._poll_job is not None:
            self.root.after_cancel(self._poll_job)
            self._poll_job = None
        self.board = chess.Board()
        self.sel, self.targets = None, {}
        self.last_move = None
        self.san_list = []
        self.thinking = self.animating = False
        self.anim_hide = None
        self.drag_from, self.drag_active = None, False
        self.flipped = self.human_color == chess.BLACK
        self.refresh_moves()
        self.draw()
        self.after_move()

    def on_new_game_click(self) -> None:
        if self.game_in_progress() and not messagebox.askyesno("New game", "Abandon the current game?"):
            return
        self.new_game()

    def on_side_change(self) -> None:
        new = chess.WHITE if self.side_var.get() == "white" else chess.BLACK
        if new == self.human_color:
            return
        if self.game_in_progress() and not messagebox.askyesno(
                "Switch sides", "Switching sides starts a new game. Continue?"):
            self.side_var.set("white" if self.human_color == chess.WHITE else "black")
            return
        self.human_color = new
        self.new_game()

    def on_elo_change(self, _event=None) -> None:
        self.bot.set_elo(int(self.elo_var.get()))

    def flip(self) -> None:
        self.flipped = not self.flipped
        self.draw()

    def undo(self) -> None:
        if self.thinking or self.animating:
            return
        n = 2 if self.board.turn == self.human_color else 1
        if len(self.board.move_stack) < n:
            return
        self.game_id += 1  # invalidate anything in flight
        for _ in range(n):
            self.board.pop()
            self.san_list.pop()
        self.last_move = self.board.peek() if self.board.move_stack else None
        self.sel, self.targets = None, {}
        self.refresh_moves()
        self.draw()
        self.after_move()

    # -------------------------------------------------------------- status --
    def refresh_moves(self) -> None:
        lines = []
        for i in range(0, len(self.san_list), 2):
            white = self.san_list[i]
            black = self.san_list[i + 1] if i + 1 < len(self.san_list) else ""
            lines.append(f"{i // 2 + 1:>3}. {white:<8}{black}")
        t = self.moves_text
        t.config(state="normal")
        t.delete("1.0", "end")
        t.insert("1.0", "\n".join(lines))
        t.see("end")
        t.config(state="disabled")

    def update_status(self) -> None:
        b = self.board
        if b.is_game_over(claim_draw=True):
            outcome = b.outcome(claim_draw=True)
            if outcome is None or outcome.winner is None:
                reason = outcome.termination.name.replace("_", " ").lower() if outcome else "draw"
                text = f"Draw ({reason})"
            elif outcome.winner == self.human_color:
                text = "Checkmate - you win!"
            else:
                text = "Checkmate - the bot wins."
        elif self.thinking:
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