# Project Na3 — automatic Stockfish analysis

This package gives the `Project-Na3` GitHub repository a free, repeatable engine-analysis workflow.

## What it does

- Checks Chess.com's public data for `chessicek`.
- Finds the newest game beginning `1.e4 c5 2.Na3`.
- Runs Stockfish at depth 18 with three candidate lines.
- Identifies the first inaccuracy and the largest evaluation swings.
- Writes a Markdown report into `reports/`.
- Commits that report to the repository automatically.
- Checks once daily and can also be started manually.

No API key, server, payment or computer is required after installation.

## One unavoidable iPhone setup

GitHub will not allow ChatGPT to write into your account without permission. Add the contents of this package to the root of your `Project-Na3` repository once.

The important paths must remain exactly:

- `.github/workflows/analyse-na3.yml`
- `scripts/analyse_latest.py`
- `requirements.txt`
- `reports/.gitkeep`

After the files are on the default branch:

1. Open the repository's **Actions** tab.
2. Select **Analyse latest Na3 game**.
3. Tap **Run workflow**.
4. Leave `latest_na3` and depth `18` selected.
5. Tap the green **Run workflow** button.

The scheduled check then runs automatically every day. When it finds no new Na3 game, it makes no commit.

## Where results appear

Open the repository and then open the `reports` folder. Each report contains:

- a practical conclusion;
- the first engine-flagged error;
- the five largest turning points;
- three candidate engine lines at critical moments;
- a move-by-move evaluation table;
- the original PGN.

## Manual options

The Actions screen allows:

- `latest_na3`: newest game where `chessicek` played White and began `1.e4 c5 2.Na3`;
- `latest_game`: newest game played by `chessicek`;
- adjustable Stockfish depth.

Depth 18 is suitable for free routine analysis. Depth 20–22 is slower but can be used for important research positions.

## Important interpretation rule

The script reports engine evidence. It does not pretend that an evaluation number is a human explanation. Project Na3 should still separate:

- engine analysis;
- database evidence;
- strategic judgement;
- practical experience.
