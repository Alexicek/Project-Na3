from __future__ import annotations

import io
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import chess
import chess.engine
import chess.pgn
import requests


USERNAME = os.getenv("CHESSCOM_USERNAME", "chessicek")
MODE = os.getenv("ANALYSIS_MODE", "latest_na3")
DEPTH = int(os.getenv("STOCKFISH_DEPTH", "18"))
STOCKFISH_PATH = os.getenv("STOCKFISH_PATH", "/usr/games/stockfish")

REPORTS_FOLDER = Path("reports")
STATE_FILE = Path("state.json")

HEADERS = {
    "User-Agent": "Project-Na3-Research/1.0",
    "Accept": "application/json",
}


def download_json(url: str) -> dict:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def read_pgn(pgn_text: str) -> chess.pgn.Game:
    game = chess.pgn.read_game(io.StringIO(pgn_text))

    if game is None:
        raise RuntimeError("The PGN could not be read.")

    return game


def belongs_to_user(game: chess.pgn.Game) -> bool:
    white = game.headers.get("White", "").lower()
    black = game.headers.get("Black", "").lower()
    username = USERNAME.lower()

    return username in {white, black}


def is_na3_game(game: chess.pgn.Game) -> bool:
    if game.headers.get("White", "").lower() != USERNAME.lower():
        return False

    board = game.board()
    moves = []

    for move in list(game.mainline_moves())[:3]:
        moves.append(board.san(move))
        board.push(move)

    return moves == ["e4", "c5", "Na3"]


def fetch_recent_games() -> list[dict]:
    archive_data = download_json(
        f"https://api.chess.com/pub/player/{USERNAME.lower()}/games/archives"
    )

    archive_urls = archive_data.get("archives", [])

    if not archive_urls:
        raise RuntimeError("No Chess.com game archives were found.")

    games = []

    # Check the three newest monthly archives.
    for archive_url in reversed(archive_urls[-3:]):
        month_data = download_json(archive_url)

        for game_data in month_data.get("games", []):
            if game_data.get("pgn"):
                games.append(game_data)

    games.sort(
        key=lambda item: int(item.get("end_time", 0)),
        reverse=True,
    )

    return games


def select_game(game_records: list[dict]) -> tuple[dict, chess.pgn.Game]:
    for record in game_records:
        game = read_pgn(record["pgn"])

        if not belongs_to_user(game):
            continue

        if MODE == "latest_game":
            return record, game

        if MODE == "latest_na3" and is_na3_game(game):
            return record, game

    raise RuntimeError(
        f"No suitable game was found using mode: {MODE}"
    )


def score_in_centipawns(
    information: dict,
    point_of_view: chess.Color = chess.WHITE,
) -> int:
    score = information["score"].pov(point_of_view)
    value = score.score(mate_score=100000)

    return int(value or 0)


def display_score(centipawns: int) -> str:
    if centipawns >= 99000:
        return "+Mate"

    if centipawns <= -99000:
        return "-Mate"

    return f"{centipawns / 100:+.2f}"


def classify_loss(loss: int) -> str:
    if loss >= 250:
        return "Blunder"

    if loss >= 120:
        return "Mistake"

    if loss >= 60:
        return "Inaccuracy"

    return "OK"


def variation_to_san(
    board: chess.Board,
    principal_variation: list[chess.Move],
    maximum_plies: int = 8,
) -> str:
    temporary_board = board.copy()
    san_moves = []

    for move in principal_variation[:maximum_plies]:
        if move not in temporary_board.legal_moves:
            break

        san_moves.append(temporary_board.san(move))
        temporary_board.push(move)

    return " ".join(san_moves)


def run_engine_analysis(game: chess.pgn.Game) -> list[dict]:
    engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)

    try:
        try:
            engine.configure(
                {
                    "Threads": 2,
                    "Hash": 256,
                }
            )
        except Exception:
            pass

        board = game.board()
        results = []

        previous_information = engine.analyse(
            board,
            chess.engine.Limit(depth=DEPTH),
            multipv=3,
        )

        if not isinstance(previous_information, list):
            previous_information = [previous_information]

        for ply_number, played_move in enumerate(
            game.mainline_moves(),
            start=1,
        ):
            mover = board.turn
            played_san = board.san(played_move)

            evaluation_before = score_in_centipawns(
                previous_information[0]
            )

            best_line = previous_information[0].get("pv", [])
            best_move = best_line[0] if best_line else None

            if best_move and best_move in board.legal_moves:
                best_move_san = board.san(best_move)
            else:
                best_move_san = ""

            candidate_lines = []

            for information in previous_information[:3]:
                candidate_lines.append(
                    {
                        "evaluation": display_score(
                            score_in_centipawns(information)
                        ),
                        "line": variation_to_san(
                            board,
                            information.get("pv", []),
                        ),
                    }
                )

            board.push(played_move)

            new_information = engine.analyse(
                board,
                chess.engine.Limit(depth=DEPTH),
                multipv=3,
            )

            if not isinstance(new_information, list):
                new_information = [new_information]

            evaluation_after = score_in_centipawns(
                new_information[0]
            )

            if mover == chess.WHITE:
                loss = max(
                    0,
                    evaluation_before - evaluation_after,
                )
            else:
                loss = max(
                    0,
                    evaluation_after - evaluation_before,
                )

            results.append(
                {
                    "ply": ply_number,
                    "move_number": (ply_number + 1) // 2,
                    "side": "White" if mover == chess.WHITE else "Black",
                    "played": played_san,
                    "evaluation": display_score(evaluation_after),
                    "evaluation_cp": evaluation_after,
                    "loss_cp": loss,
                    "classification": classify_loss(loss),
                    "best_move": best_move_san,
                    "candidate_lines": candidate_lines,
                    "fen": board.fen(),
                }
            )

            previous_information = new_information

        return results

    finally:
        engine.quit()


def safe_filename(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text)


def make_report(
    game_record: dict,
    game: chess.pgn.Game,
    analysis: list[dict],
) -> str:
    user_is_white = (
        game.headers.get("White", "").lower() == USERNAME.lower()
    )

    user_side = "White" if user_is_white else "Black"

    user_moves = [
        row for row in analysis
        if row["side"] == user_side
    ]

    important_moves = sorted(
        user_moves,
        key=lambda row: row["loss_cp"],
        reverse=True,
    )[:5]

    first_problem = next(
        (
            row
            for row in user_moves
            if row["classification"] != "OK"
        ),
        None,
    )

    lines = []

    lines.append("# Project Na3 Stockfish report")
    lines.append("")
    lines.append(
        f"**Game:** {game.headers.get('White', 'White')} "
        f"vs {game.headers.get('Black', 'Black')}"
    )
    lines.append("")
    lines.append(
        f"**Date:** {game.headers.get('Date', 'Unknown')}"
    )
    lines.append("")
    lines.append(
        f"**Result:** {game.headers.get('Result', '*')}"
    )
    lines.append("")
    lines.append(
        f"**Chess.com game:** {game_record.get('url', 'Unavailable')}"
    )
    lines.append("")
    lines.append(
        f"**Engine setting:** Stockfish depth {DEPTH}, MultiPV 3"
    )
    lines.append("")

    lines.append("## Practical conclusion")
    lines.append("")

    if first_problem:
        dots = "." if first_problem["side"] == "White" else "..."
        move_name = (
            f"{first_problem['move_number']}"
            f"{dots}{first_problem['played']}"
        )

        lines.append(
            f"The first engine-flagged problem for {USERNAME} was "
            f"**{move_name}**."
        )
        lines.append("")
        lines.append(
            f"It was classified as **"
            f"{first_problem['classification']}** "
            f"with an estimated loss of "
            f"{first_problem['loss_cp'] / 100:.2f} pawns."
        )
    else:
        lines.append(
            "No move crossed the configured inaccuracy threshold."
        )

    lines.append("")
    lines.append("## Biggest turning points")
    lines.append("")

    for row in important_moves:
        dots = "." if row["side"] == "White" else "..."
        move_name = (
            f"{row['move_number']}{dots}{row['played']}"
        )

        lines.append(
            f"### {move_name} — {row['classification']}"
        )
        lines.append("")
        lines.append(
            f"- Evaluation after the move: **{row['evaluation']}**"
        )
        lines.append(
            f"- Estimated loss: "
            f"**{row['loss_cp'] / 100:.2f} pawns**"
        )

        if row["best_move"]:
            lines.append(
                f"- Stockfish first choice: **{row['best_move']}**"
            )

        lines.append("- Candidate engine lines:")

        for candidate in row["candidate_lines"]:
            lines.append(
                f"  - `{candidate['evaluation']}` — "
                f"{candidate['line']}"
            )

        lines.append("")

    lines.append("## Move-by-move table")
    lines.append("")
    lines.append(
        "| Move | Played | Evaluation | Loss | Classification | Best move |"
    )
    lines.append(
        "|---|---|---:|---:|---|---|"
    )

    for row in analysis:
        dots = "." if row["side"] == "White" else "..."
        move_label = f"{row['move_number']}{dots}"

        lines.append(
            f"| {move_label} | {row['played']} | "
            f"{row['evaluation']} | "
            f"{row['loss_cp'] / 100:.2f} | "
            f"{row['classification']} | "
            f"{row['best_move']} |"
        )

    lines.append("")
    lines.append("## PGN")
    lines.append("")
    lines.append("```pgn")

    exporter = chess.pgn.StringExporter(
        headers=True,
        variations=False,
        comments=False,
    )

    lines.append(game.accept(exporter))
    lines.append("```")
    lines.append("")
    lines.append(
        "> Engine scores are evidence, not strategic explanations. "
        "Project Na3 should discuss database evidence, human judgement "
        "and practical experience separately."
    )

    return "\n".join(lines)


def main() -> None:
    REPORTS_FOLDER.mkdir(exist_ok=True)

    game_records = fetch_recent_games()
    game_record, game = select_game(game_records)

    game_identifier = (
        f"{game_record.get('end_time', 0)}:"
        f"{game.headers.get('White', '')}:"
        f"{game.headers.get('Black', '')}"
    )

    old_state = {}

    if STATE_FILE.exists():
        try:
            old_state = json.loads(STATE_FILE.read_text())
        except Exception:
            old_state = {}

    if old_state.get("last_analysed_game") == game_identifier:
        print("The latest matching game has already been analysed.")
        return

    print(
        f"Analysing {game.headers.get('White')} "
        f"vs {game.headers.get('Black')}..."
    )

    analysis = run_engine_analysis(game)

    date = game.headers.get("Date", "unknown").replace(".", "-")
    white = safe_filename(
        game.headers.get("White", "White")
    )
    black = safe_filename(
        game.headers.get("Black", "Black")
    )

    filename = (
        f"{date}_{white}_vs_{black}_"
        f"{game_record.get('end_time', 0)}.md"
    )

    report_path = REPORTS_FOLDER / filename

    report_path.write_text(
        make_report(game_record, game, analysis),
        encoding="utf-8",
    )

    STATE_FILE.write_text(
        json.dumps(
            {
                "last_analysed_game": game_identifier,
                "last_report": str(report_path),
                "analysed_at_utc": datetime.now(
                    timezone.utc
                ).isoformat(),
                "mode": MODE,
                "depth": DEPTH,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Report created: {report_path}")


if __name__ == "__main__":
    main()
