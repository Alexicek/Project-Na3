#!/bin/sh
python3 na3_game_fetcher.py --na3 --months 6 --latest 5 --output latest_na3_games.pgn
echo "Finished. Upload latest_na3_games.pgn to Project Na3."
