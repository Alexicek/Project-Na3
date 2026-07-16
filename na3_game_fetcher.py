#!/usr/bin/env python3
"""
Project Na3 Chess.com Game Fetcher

Fetches recent public Chess.com games for a player and optionally filters
for games beginning 1.e4 c5 2.Na3.

Uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable

API_ROOT = "https://api.chess.com/pub"
DEFAULT_USER_AGENT = "Project-Na3-Game-Fetcher/1.0 (personal research tool)"


def api_get_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(response.read().decode(charset))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError(f"Chess.com returned 404 for: {url}") from exc
        if exc.code == 429:
            raise RuntimeError("Chess.com rate-limited the request. Try again shortly.") from exc
        raise RuntimeError(f"Chess.com API error {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Chess.com: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("Chess.com returned data that was not valid JSON.") from exc


def month_pairs(months_back: int) -> list[tuple[int, int]]:
    if months_back < 1:
        raise ValueError("--months must be at least 1")
    today = dt.datetime.now(dt.timezone.utc)
    year, month = today.year, today.month
    pairs: list[tuple[int, int]] = []
    for _ in range(months_back):
        pairs.append((year, month))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return pairs


def fetch_month(username: str, year: int, month: int) -> list[dict[str, Any]]:
    url = f"{API_ROOT}/player/{username.lower()}/games/{year:04d}/{month:02d}"
    payload = api_get_json(url)
    games = payload.get("games", [])
    if not isinstance(games, list):
        raise RuntimeError(f"Unexpected API response for {year:04d}-{month:02d}")
    return games


def fetch_recent_games(username: str, months_back: int) -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
    for index, (year, month) in enumerate(month_pairs(months_back)):
        try:
            games.extend(fetch_month(username, year, month))
        except RuntimeError as exc:
            print(f"Warning: {exc}", file=sys.stderr)
        if index + 1 < months_back:
            time.sleep(0.15)

    # Chess.com end_time is Unix time. Use start_time as fallback.
    games.sort(
        key=lambda game: int(game.get("end_time") or game.get("start_time") or 0),
        reverse=True,
    )
    return games


HEADER_RE = re.compile(r'^\[(\w+)\s+"(.*)"\]$', re.MULTILINE)


def parse_headers(pgn: str) -> dict[str, str]:
    return dict(HEADER_RE.findall(pgn))


def clean_movetext(pgn: str) -> str:
    # Remove PGN headers.
    text = re.sub(r'^\[.*?\]\s*$', ' ', pgn, flags=re.MULTILINE)
    # Remove brace comments and semicolon comments.
    text = re.sub(r'\{[^}]*\}', ' ', text, flags=re.DOTALL)
    text = re.sub(r';[^\n]*', ' ', text)
    # Remove recursive parenthesized variations.
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r'\([^()]*\)', ' ', text)
    # Remove NAGs and move numbers.
    text = re.sub(r'\$\d+', ' ', text)
    text = re.sub(r'\b\d+\.(?:\.\.)?', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def san_moves(pgn: str) -> list[str]:
    results = {"1-0", "0-1", "1/2-1/2", "*"}
    return [
        token
        for token in clean_movetext(pgn).split()
        if token not in results and not token.startswith("$")
    ]


def normalise_san(move: str) -> str:
    # Ignore check/mate and annotation suffixes for opening-prefix matching.
    return re.sub(r'[+#?!]+$', '', move.strip())


def has_prefix(pgn: str, prefix: Iterable[str]) -> bool:
    moves = [normalise_san(move) for move in san_moves(pgn)]
    wanted = [normalise_san(move) for move in prefix]
    return moves[: len(wanted)] == wanted


def player_colour(game: dict[str, Any], username: str) -> str:
    target = username.casefold()
    white = str(game.get("white", {}).get("username", "")).casefold()
    black = str(game.get("black", {}).get("username", "")).casefold()
    if white == target:
        return "White"
    if black == target:
        return "Black"
    return "Unknown"


def result_for_player(game: dict[str, Any], username: str) -> str:
    colour = player_colour(game, username)
    side = game.get(colour.lower(), {}) if colour in {"White", "Black"} else {}
    result = side.get("result", "unknown")
    if result == "win":
        return "Win"
    draw_results = {
        "agreed", "repetition", "stalemate", "insufficient",
        "50move", "timevsinsufficient"
    }
    if result in draw_results:
        return "Draw"
    return "Loss" if result != "unknown" else "Unknown"


def format_utc(unix_time: int | None) -> str:
    if not unix_time:
        return "unknown date"
    return dt.datetime.fromtimestamp(int(unix_time), tz=dt.timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


def game_summary(game: dict[str, Any], username: str, number: int) -> str:
    headers = parse_headers(game.get("pgn", ""))
    white = game.get("white", {}).get("username", headers.get("White", "?"))
    black = game.get("black", {}).get("username", headers.get("Black", "?"))
    colour = player_colour(game, username)
    result = result_for_player(game, username)
    time_class = game.get("time_class", "unknown")
    rules = game.get("rules", "chess")
    opening = headers.get("ECOUrl", headers.get("ECO", ""))
    first_moves = " ".join(san_moves(game.get("pgn", ""))[:10])
    return (
        f"{number}. {format_utc(game.get('end_time'))} | {time_class} | "
        f"{white} vs {black} | {username}: {colour}, {result}\n"
        f"   First moves: {first_moves or 'unavailable'}\n"
        f"   URL: {game.get('url', 'unavailable')}\n"
        f"   Rules: {rules}" + (f" | Opening: {opening}" if opening else "")
    )


def joined_pgn(games: list[dict[str, Any]]) -> str:
    return "\n\n".join(game.get("pgn", "").strip() for game in games if game.get("pgn")) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch recent Chess.com games and filter Project Na3 games."
    )
    parser.add_argument("--username", default="Chessicek")
    parser.add_argument(
        "--months", type=int, default=3,
        help="How many calendar months to inspect (default: 3)."
    )
    parser.add_argument(
        "--latest", type=int, default=20,
        help="Maximum games to show/export after filtering (default: 20)."
    )
    parser.add_argument(
        "--na3", action="store_true",
        help="Keep only games beginning 1.e4 c5 2.Na3."
    )
    parser.add_argument(
        "--white-only", action="store_true",
        help="Keep only games where the specified player was White."
    )
    parser.add_argument(
        "--time-class",
        choices=["daily", "rapid", "blitz", "bullet"],
        help="Optional Chess.com time-class filter."
    )
    parser.add_argument(
        "--output", type=Path,
        help="Write all selected games to this PGN file."
    )
    parser.add_argument(
        "--json-output", type=Path,
        help="Also save selected raw Chess.com records as JSON."
    )
    args = parser.parse_args()

    try:
        games = fetch_recent_games(args.username, args.months)
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.white_only:
        games = [g for g in games if player_colour(g, args.username) == "White"]
    if args.time_class:
        games = [g for g in games if g.get("time_class") == args.time_class]
    if args.na3:
        games = [
            g for g in games
            if has_prefix(g.get("pgn", ""), ["e4", "c5", "Na3"])
        ]

    selected = games[: max(args.latest, 0)]

    label = "Na3 games" if args.na3 else "games"
    print(
        f"Found {len(games)} matching {label} across the last "
        f"{args.months} calendar month(s). Showing {len(selected)}.\n"
    )
    for i, game in enumerate(selected, start=1):
        print(game_summary(game, args.username, i))
        print()

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(joined_pgn(selected), encoding="utf-8")
        print(f"Saved PGN: {args.output}")

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(selected, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Saved JSON: {args.json_output}")

    if not selected:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
