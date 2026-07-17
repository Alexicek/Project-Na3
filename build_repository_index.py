#!/usr/bin/env python3
"""
Build the Project Na3 machine-readable repository index.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
HEADER_RE = re.compile(r'^\[(\w+)\s+"(.*)"\]$', re.MULTILINE)


def read_json(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path.name} must contain a JSON list")
    return data


def parse_headers(pgn: str) -> dict[str, str]:
    return dict(HEADER_RE.findall(pgn or ""))


def unix_iso(value: Any) -> str | None:
    try:
        stamp = int(value)
    except (TypeError, ValueError):
        return None
    return dt.datetime.fromtimestamp(
        stamp, tz=dt.timezone.utc
    ).isoformat().replace("+00:00", "Z")


def player_colour(game: dict[str, Any], username: str) -> str:
    target = username.casefold()
    if str(game.get("white", {}).get("username", "")).casefold() == target:
        return "White"
    if str(game.get("black", {}).get("username", "")).casefold() == target:
        return "Black"
    return "Unknown"


def practical_result(game: dict[str, Any], username: str) -> str:
    colour = player_colour(game, username)
    if colour == "Unknown":
        return "Unknown"

    result_code = game.get(colour.lower(), {}).get("result")

    if result_code == "win":
        return "Win"

    if result_code in {
        "agreed",
        "repetition",
        "stalemate",
        "insufficient",
        "50move",
        "timevsinsufficient",
    }:
        return "Draw"

    return "Loss" if result_code else "Unknown"


def pgn_result(game: dict[str, Any]) -> str:
    return parse_headers(game.get("pgn", "")).get("Result", "*")


def opening_name(game: dict[str, Any]) -> str:
    headers = parse_headers(game.get("pgn", ""))
    eco_url = headers.get("ECOUrl", "")
    if eco_url:
        return eco_url.rsplit("/", 1)[-1].replace("-", " ")
    return headers.get("ECO", "")


def game_record(game: dict[str, Any], username: str, pgn_path=None):
    headers = parse_headers(game.get("pgn", ""))

    white = game.get("white", {})
    black = game.get("black", {})

    record = {
        "end_time": unix_iso(game.get("end_time")),
        "date": headers.get("Date"),
        "white": white.get("username", headers.get("White")),
        "white_rating": white.get("rating"),
        "black": black.get("username", headers.get("Black")),
        "black_rating": black.get("rating"),
        "result": pgn_result(game),
        "user_colour": player_colour(game, username),
        "user_result": practical_result(game, username),
        "time_class": game.get("time_class"),
        "time_control": game.get("time_control"),
        "rated": game.get("rated"),
        "opening": opening_name(game),
        "url": game.get("url"),
    }

    if pgn_path:
        record["pgn"] = pgn_path

    return record


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def copy_file(source: Path, destination: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)

    if source.exists():
        shutil.copyfile(source, destination)
    else:
        destination.write_text("", encoding="utf-8")


def main():
    username = "Chessicek"

    all_games = read_json(ROOT / "latest_games.json")
    na3_games = read_json(ROOT / "latest_na3_games.json")

    copy_file(ROOT / "latest_games.pgn", ROOT / "games/latest.pgn")
    write_json(ROOT / "games/latest.json", all_games)

    copy_file(ROOT / "latest_na3_games.pgn", ROOT / "na3/latest_na3.pgn")
    write_json(ROOT / "na3/latest_na3.json", na3_games)

    write_json(
        ROOT / "na3/history.json",
        [game_record(game, username) for game in na3_games],
    )

    index = {
        "schema_version": 1,
        "username": username,
        "last_updated": dt.datetime.now(dt.timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        "latest_game": (
            game_record(all_games[0], username, "games/latest.pgn")
            if all_games else None
        ),
        "latest_na3": (
            game_record(na3_games[0], username, "na3/latest_na3.pgn")
            if na3_games else None
        ),
        "counts": {
            "recent_games": len(all_games),
            "recent_na3_games": len(na3_games),
        },
        "files": {
            "recent_games_json": "games/latest.json",
            "recent_games_pgn": "games/latest.pgn",
            "latest_na3_json": "na3/latest_na3.json",
            "latest_na3_pgn": "na3/latest_na3.pgn",
            "na3_history": "na3/history.json",
        },
    }

    write_json(ROOT / "index.json", index)

    print(
        f"Built index.json with {len(all_games)} recent games "
        f"and {len(na3_games)} Na3 games."
    )


if __name__ == "__main__":
    main()
