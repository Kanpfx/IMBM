"""IMBM local-game entry point."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from sc2 import maps
from sc2.data import AIBuild, Difficulty, Race
from sc2.main import run_game
from sc2.player import Bot, Computer
from loguru import logger

sys.path.extend(["ares-sc2/src/ares", "ares-sc2/src", "ares-sc2"])

from bot.main import MyBot
from config.env import load_environment, require_environment


def configure_console_logging() -> None:
    """Keep the live game console readable; detailed traces stay in telemetry."""
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        colorize=False,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} {message}",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the LLM-controlled IMBM bot.")
    parser.add_argument("--map_name", required=True, help="Installed SC2 map name.")
    parser.add_argument(
        "--difficulty",
        choices=[difficulty.name for difficulty in Difficulty],
        default="Hard",
        help="Built-in opponent difficulty.",
    )
    parser.add_argument(
        "--ai_build",
        choices=[build.name for build in AIBuild],
        default="RandomBuild",
        help="Built-in opponent build style.",
    )
    parser.add_argument("--player_name", default="im_bm_player")
    parser.add_argument("--own_race", choices=["Terran"], default="Terran")
    parser.add_argument(
        "--enemy_race", choices=["Terran", "Zerg", "Protoss"], default="Terran"
    )
    parser.add_argument(
        "-bm",
        "--enable_bm",
        action="store_true",
        help="Enable the asynchronous Brain Module strategic adviser.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_console_logging()
    load_environment()
    require_environment(["LLM_IMBM_MODEL", "LLM_IMBM_BASE_URL", "LLM_IMBM_API_KEY"])
    own_race = Race[args.own_race]
    enemy_race = Race[args.enemy_race]
    match_log_directory = Path("logs") / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    match_log_directory.mkdir(parents=True, exist_ok=False)
    bot = Bot(
        own_race,
        MyBot(
            enable_bm=args.enable_bm,
            run_metadata={
                "map_name": args.map_name,
                "difficulty": args.difficulty,
                "ai_build": args.ai_build,
                "player_name": args.player_name,
                "own_race": args.own_race,
                "enemy_race": args.enemy_race,
            },
            log_directory=match_log_directory,
        ),
        args.player_name,
    )
    opponent = Computer(
        enemy_race,
        Difficulty[args.difficulty],
        ai_build=AIBuild[args.ai_build],
    )
    run_game(
        maps.get(args.map_name),
        [bot, opponent],
        realtime=False,
        save_replay_as=str(match_log_directory / "replay.SC2Replay"),
    )


if __name__ == "__main__":
    main()
