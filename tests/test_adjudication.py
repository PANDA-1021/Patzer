import chess

from patzer.tools.calibrate import material_balance, play_game


def test_material_balance():
    assert material_balance(chess.Board()) == 0
    no_black_queen = chess.Board("rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    assert material_balance(no_black_queen) == 900


def _task(fen, bot_color, max_plies):
    return {"seed": 1, "fen": fen, "bot_elo": 1000, "bot_color": bot_color,
            "opp": {"kind": "bot", "setting": 1000}, "movetime": 0.1, "max_plies": max_plies}


def test_move_limit_with_a_big_material_edge_is_a_win():
    fen = "4k3/8/8/8/8/8/8/3QK3 w - - 0 1"          # White is up a queen
    score, pgn, ended, plies = play_game(_task(fen, chess.WHITE, 2))
    assert (score, ended, plies) == (1.0, "adjudicated", 2)
    score, _, ended, _ = play_game(_task(fen, chess.BLACK, 2))   # same position, bot on the losing side
    assert (score, ended) == (0.0, "adjudicated")


def test_move_limit_with_equal_material_is_a_draw():
    score, _, ended, _ = play_game(_task(chess.STARTING_FEN, chess.WHITE, 2))
    assert (score, ended) == (0.5, "move_limit")
