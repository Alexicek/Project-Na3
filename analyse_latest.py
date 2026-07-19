from __future__ import annotations

import io
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import chess
import chess.engine
import chess.pgn
import requests


USERNAME = os.getenv("CHESSCOM_USERNAME", "chessicek")
MODE = os.getenv("ANALYSIS_MODE", "latest_na3")
DEPTH = int(os.getenv("STOCKFISH_DEPTH", "18"))
STOCKFISH_PATH = os.getenv("STOCKFISH_PATH", "/usr/games/stockfish")

REPORTS_DIR = Path("reports")
STATE_FILE = Path("state.json")
INDEX_FILE = Path("analysis_index.json")
PATTERNS_FILE = Path("recurring_patterns.json")

HEADERS = {
    "User-Agent": "Project-Na3-Research/1.0",
    "Accept": "application/json",
}


def get_json(url: str) -> dict[str, Any]:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def parse_game(pgn_text: str) -> chess.pgn.Game:
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        raise RuntimeError("Could not parse the Chess.com PGN.")
    return game


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def game_belongs_to_user(game: chess.pgn.Game) -> bool:
    username = USERNAME.lower()
    return username in {
        game.headers.get("White", "").lower(),
        game.headers.get("Black", "").lower(),
    }


def user_is_white(game: chess.pgn.Game) -> bool:
    return game.headers.get("White", "").lower() == USERNAME.lower()


def first_san_moves(game: chess.pgn.Game, count: int) -> list[str]:
    board = game.board()
    result: list[str] = []
    for move in list(game.mainline_moves())[:count]:
        result.append(board.san(move))
        board.push(move)
    return result


def is_na3_game(game: chess.pgn.Game) -> bool:
    return user_is_white(game) and first_san_moves(game, 3) == ["e4", "c5", "Na3"]


def fetch_recent_game_records() -> list[dict[str, Any]]:
    archive_data = get_json(
        f"https://api.chess.com/pub/player/{USERNAME.lower()}/games/archives"
    )
    archive_urls = archive_data.get("archives", [])
    if not archive_urls:
        raise RuntimeError(f"No Chess.com archives found for {USERNAME}.")

    records: list[dict[str, Any]] = []
    for archive_url in reversed(archive_urls[-3:]):
        month_data = get_json(archive_url)
        records.extend(
            record
            for record in month_data.get("games", [])
            if record.get("pgn")
        )

    records.sort(key=lambda item: int(item.get("end_time", 0)), reverse=True)
    return records


def select_game(records: list[dict[str, Any]]) -> tuple[dict[str, Any], chess.pgn.Game]:
    for record in records:
        game = parse_game(record["pgn"])
        if not game_belongs_to_user(game):
            continue
        if MODE == "latest_game":
            return record, game
        if MODE == "latest_na3" and is_na3_game(game):
            return record, game

    raise RuntimeError(f"No matching game found for mode '{MODE}'.")


def score_cp(info: dict[str, Any], pov: chess.Color = chess.WHITE) -> int:
    score = info["score"].pov(pov).score(mate_score=100000)
    return int(score or 0)


def format_eval(cp: int) -> str:
    if cp >= 99000:
        return "+Mate"
    if cp <= -99000:
        return "-Mate"
    return f"{cp / 100:+.2f}"


def classify_loss(loss_cp: int) -> str:
    if loss_cp >= 250:
        return "Blunder"
    if loss_cp >= 120:
        return "Mistake"
    if loss_cp >= 60:
        return "Inaccuracy"
    return "OK"


def pv_to_san(board: chess.Board, pv: list[chess.Move], max_plies: int = 8) -> str:
    clone = board.copy()
    san: list[str] = []
    for move in pv[:max_plies]:
        if move not in clone.legal_moves:
            break
        san.append(clone.san(move))
        clone.push(move)
    return " ".join(san)


def analyse_game(game: chess.pgn.Game) -> list[dict[str, Any]]:
    engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
    try:
        try:
            engine.configure({"Threads": 2, "Hash": 256})
        except Exception:
            pass

        board = game.board()
        rows: list[dict[str, Any]] = []

        previous = engine.analyse(
            board,
            chess.engine.Limit(depth=DEPTH),
            multipv=3,
        )
        if not isinstance(previous, list):
            previous = [previous]

        for ply, move in enumerate(game.mainline_moves(), start=1):
            mover = board.turn
            played = board.san(move)
            before_cp = score_cp(previous[0])

            pv = previous[0].get("pv", [])
            best_move = pv[0] if pv else None
            best_san = board.san(best_move) if best_move in board.legal_moves else ""

            candidates = [
                {
                    "evaluation": format_eval(score_cp(info)),
                    "line": pv_to_san(board, info.get("pv", [])),
                }
                for info in previous[:3]
            ]

            board.push(move)

            after = engine.analyse(
                board,
                chess.engine.Limit(depth=DEPTH),
                multipv=3,
            )
            if not isinstance(after, list):
                after = [after]

            after_cp = score_cp(after[0])
            loss_cp = (
                max(0, before_cp - after_cp)
                if mover == chess.WHITE
                else max(0, after_cp - before_cp)
            )

            rows.append(
                {
                    "ply": ply,
                    "move_number": (ply + 1) // 2,
                    "side": "White" if mover == chess.WHITE else "Black",
                    "played": played,
                    "evaluation": format_eval(after_cp),
                    "evaluation_cp": after_cp,
                    "loss_cp": loss_cp,
                    "classification": classify_loss(loss_cp),
                    "best_move": best_san,
                    "candidate_lines": candidates,
                    "fen_after": board.fen(),
                }
            )
            previous = after

        return rows
    finally:
        engine.quit()


def detect_patterns(user_rows: list[dict[str, Any]]) -> list[str]:
    patterns: list[str] = []

    for row in user_rows:
        move = row["played"]
        classification = row["classification"]
        loss = row["loss_cp"]

        if classification == "OK":
            continue

        if move.startswith("d5") or move.startswith("e5"):
            patterns.append("premature central pawn advance")

        if move.startswith("Nb6") or move.startswith("Na4") or move.startswith("Nc4"):
            patterns.append("knight relocation created tactical or positional risk")

        if move.startswith("Q"):
            patterns.append("queen move lost time or created tactical exposure")

        if loss >= 250:
            patterns.append("forcing-move oversight")

    return patterns


def safe_filename(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text)


def move_label(row: dict[str, Any]) -> str:
    dots = "." if row["side"] == "White" else "..."
    return f"{row['move_number']}{dots}{row['played']}"


def build_report(
    record: dict[str, Any],
    game: chess.pgn.Game,
    rows: list[dict[str, Any]],
    patterns: list[str],
) -> str:
    side = "White" if user_is_white(game) else "Black"
    user_rows = [row for row in rows if row["side"] == side]
    critical = sorted(user_rows, key=lambda row: row["loss_cp"], reverse=True)[:5]
    first_problem = next(
        (row for row in user_rows if row["classification"] != "OK"),
        None,
    )

    report: list[str] = []
    report.append("# Project Na3 analysis report")
    report.append("")
    report.append(f"- **Game:** {game.headers.get('White')} vs {game.headers.get('Black')}")
    report.append(f"- **Date:** {game.headers.get('Date', 'Unknown')}")
    report.append(f"- **Result:** {game.headers.get('Result', '*')}")
    report.append(f"- **Chess.com:** {record.get('url', 'Unavailable')}")
    report.append(f"- **Engine evidence:** Stockfish depth {DEPTH}, MultiPV 3")
    report.append("")

    report.append("## Practical conclusion")
    report.append("")
    if first_problem:
        report.append(
            f"The first engine-flagged problem for {USERNAME} was "
            f"**{move_label(first_problem)}**: "
            f"{first_problem['classification'].lower()}, "
            f"approximately {first_problem['loss_cp'] / 100:.2f} pawns."
        )
    else:
        report.append("No move crossed the configured inaccuracy threshold.")
    report.append("")

    report.append("## Engine turning points")
    report.append("")
    for row in critical:
        report.append(f"### {move_label(row)} â {row['classification']}")
        report.append("")
        report.append(f"- Evaluation after the move: **{row['evaluation']}**")
        report.append(f"- Estimated loss: **{row['loss_cp'] / 100:.2f} pawns**")
        if row["best_move"]:
            report.append(f"- Stockfish first choice: **{row['best_move']}**")
        report.append("- Candidate lines:")
        for candidate in row["candidate_lines"]:
            report.append(
                f"  - `{candidate['evaluation']}` â {candidate['line']}"
            )
        report.append("")

    report.append("## Automatically detected practical patterns")
    report.append("")
    if patterns:
        for pattern in sorted(set(patterns)):
            report.append(f"- {pattern}")
    else:
        report.append("- No recurring pattern detected from this game alone.")
    report.append("")

    report.append("## Move-by-move engine table")
    report.append("")
    report.append("| Move | Played | Eval | Loss | Label | Best move |")
    report.append("|---:|---|---:|---:|---|---|")
    for row in rows:
        dots = "." if row["side"] == "White" else "..."
        report.append(
            f"| {row['move_number']}{dots} | {row['played']} | "
            f"{row['evaluation']} | {row['loss_cp'] / 100:.2f} | "
            f"{row['classification']} | {row['best_move']} |"
        )
    report.append("")

    report.append("## PGN")
    report.append("")
    report.append("```pgn")
    exporter = chess.pgn.StringExporter(
        headers=True,
        variations=False,
        comments=False,
    )
    report.append(game.accept(exporter))
    report.append("```")
    report.append("")
    report.append(
        "> This report contains engine evidence and automatic pattern detection. "
        "Human strategic judgement, database evidence and repertoire conclusions "
        "must still be added separately."
    )
    return "\n".join(report)


def update_index(
    report_path: Path,
    record: dict[str, Any],
    game: chess.pgn.Game,
    rows: list[dict[str, Any]],
) -> None:
    index = load_json(INDEX_FILE, {"games": []})
    game_key = f"{record.get('end_time', 0)}:{game.headers.get('White')}:{game.headers.get('Black')}"

    if any(item.get("game_key") == game_key for item in index["games"]):
        return

    user_side = "White" if user_is_white(game) else "Black"
    user_rows = [row for row in rows if row["side"] == user_side]
    worst = max(user_rows, key=lambda row: row["loss_cp"], default=None)

    index["games"].append(
        {
            "game_key": game_key,
            "date": game.headers.get("Date", "Unknown"),
            "white": game.headers.get("White", ""),
            "black": game.headers.get("Black", ""),
            "result": game.headers.get("Result", "*"),
            "url": record.get("url", ""),
            "report": str(report_path),
            "worst_move": move_label(worst) if worst else None,
            "worst_loss_cp": worst["loss_cp"] if worst else 0,
        }
    )
    save_json(INDEX_FILE, index)


def update_patterns(patterns: list[str]) -> None:
    existing = load_json(PATTERNS_FILE, {"counts": {}})
    counts = Counter(existing.get("counts", {}))
    counts.update(patterns)
    save_json(PATTERNS_FILE, {"counts": dict(counts.most_common())})


def main() -> None:
    REPORTS_DIR.mkdir(exist_ok=True)

    records = fetch_recent_game_records()
    record, game = select_game(records)

    game_key = (
        f"{record.get('end_time', 0)}:"
        f"{game.headers.get('White', '')}:"
        f"{game.headers.get('Black', '')}"
    )

    state = load_json(STATE_FILE, {})
    if MODE == "latest_na3" and state.get("last_analysed_game") == game_key:
        print("Latest matching game has already been analysed.")
        return

    print(
        f"Analysing {game.headers.get('White')} vs "
        f"{game.headers.get('Black')} at depth {DEPTH}..."
    )

    rows = analyse_game(game)
    user_side = "White" if user_is_white(game) else "Black"
    user_rows = [row for row in rows if row["side"] == user_side]
    patterns = detect_patterns(user_rows)

    date = game.headers.get("Date", "unknown").replace(".", "-")
    white = safe_filename(game.headers.get("White", "White"))
    black = safe_filename(game.headers.get("Black", "Black"))
    report_path = REPORTS_DIR / (
        f"{date}_{white}_vs_{black}_{record.get('end_time', 0)}.md"
    )

    report_path.write_text(
        build_report(record, game, rows, patterns),
        encoding="utf-8",
    )

    update_index(report_path, record, game, rows)
    update_patterns(patterns)

    save_json(
        STATE_FILE,
        {
            "last_analysed_game": game_key,
            "last_report": str(report_path),
            "analysed_at_utc": datetime.now(timezone.utc).isoformat(),
            "mode": MODE,
            "depth": DEPTH,
        },
    )

    print(f"Report created: {report_path}")


if __name__ == "__main__":
    main()
