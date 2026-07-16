# Project Na3 Chess.com Game Fetcher

A lightweight command-line tool for retrieving public games from Chess.com and
finding games that begin:

`1.e4 c5 2.Na3`

The default username is **Chessicek**.

## Requirements

- Python 3.9 or newer
- Internet connection
- No third-party packages

## Fastest use

Open Terminal / PowerShell in this folder and run:

```bash
python na3_game_fetcher.py --na3 --output chessicek_na3_games.pgn
```

This searches the current month plus the previous two calendar months, prints
the matching games, and saves them in one PGN file.

## Useful commands

Latest 20 games:

```bash
python na3_game_fetcher.py
```

Latest Na3 games from the last 12 calendar months:

```bash
python na3_game_fetcher.py --na3 --months 12
```

Latest five rapid Na3 games:

```bash
python na3_game_fetcher.py --na3 --time-class rapid --latest 5
```

Save both PGN and raw JSON:

```bash
python na3_game_fetcher.py --na3 --months 12 \
  --output chessicek_na3_games.pgn \
  --json-output chessicek_na3_games.json
```

Use another Chess.com account:

```bash
python na3_game_fetcher.py --username AnotherName --na3
```

## Recommended Project Na3 workflow

1. Run:

```bash
python na3_game_fetcher.py --na3 --months 6 --latest 5 \
  --output latest_na3_games.pgn
```

2. Upload `latest_na3_games.pgn` to the Project Na3 chat.
3. Ask: **Analyse my latest Na3 game.**

The tool sorts games newest first, so the first PGN is the latest matching game.

## Notes

- Chess.com’s public API is read-only and only returns public game data.
- A just-finished game may take a short time to appear in the monthly archive.
- `--months` means calendar months, including the current month.
- Opening matching ignores check, mate, and annotation suffixes.
