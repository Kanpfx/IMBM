"""IMBM local-game entry point."""

from __future__ import annotations

import argparse
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import TextIO

from loguru import logger
from sc2 import maps
from sc2.data import AIBuild, Difficulty, Race
from sc2.main import run_game
from sc2.player import Bot, Computer

sys.path.extend(["ares-sc2/src/ares", "ares-sc2/src", "ares-sc2"])

from config.env import load_environment, require_environment
from game.bot.main import MyBot
from knowledge.loader import available_tactics


class _TeeStream:
    """Write one console stream to its original destination and a UTF-8 log."""

    def __init__(self, stream: TextIO, mirror: TextIO, lock: Lock):
        self._stream = stream
        self._mirror = mirror
        self._lock = lock

    def write(self, text: str) -> int:
        with self._lock:
            written = self._stream.write(text)
            self._mirror.write(text)
            self._mirror.flush()
        return written

    def flush(self) -> None:
        with self._lock:
            self._stream.flush()
            self._mirror.flush()

    def __getattr__(self, name: str):
        return getattr(self._stream, name)


@contextmanager
def mirror_console(path: Path):
    """Mirror stdout and stderr verbatim while preserving the live console."""
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    lock = Lock()
    with path.open("a", encoding="utf-8", buffering=1) as mirror:
        sys.stdout = _TeeStream(original_stdout, mirror, lock)
        sys.stderr = _TeeStream(original_stderr, mirror, lock)
        try:
            yield
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr


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
        "--build_mode",
        choices=[build.name for build in AIBuild],
        default="RandomBuild",
        help="Built-in opponent build style.",
    )
    parser.add_argument(
        "--tactic",
        choices=available_tactics(),
        default="BattleCruiserRush",
        help="Tactic card used by BM.",
    )
    parser.add_argument("--player_name", default="im_bm_player")
    parser.add_argument("--own_race", choices=["Terran"], default="Terran")
    parser.add_argument(
        "--enemy_race", choices=["Terran", "Zerg", "Protoss"], default="Terran"
    )
    parser.add_argument(
        "-bm",
        "--bm",
        "--enable_bm",
        dest="enable_bm",
        action="store_true",
        help="Enable BM guidance (blocking first response, then async refreshes).",
    )
    return parser.parse_args()


def main() -> None:
    load_environment()
    args = parse_args()
    require_environment(["LLM_IMBM_MODEL", "LLM_IMBM_BASE_URL", "LLM_IMBM_API_KEY"])
    own_race = Race[args.own_race]
    enemy_race = Race[args.enemy_race]
    match_log_directory = Path("logs") / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    match_log_directory.mkdir(parents=True, exist_ok=False)
    with mirror_console(match_log_directory / "console.log"):
        configure_console_logging()
        try:
            bot = Bot(
                own_race,
                MyBot(
                    tactic_name=args.tactic,
                    enable_bm=args.enable_bm,
                    run_metadata={
                        "map_name": args.map_name,
                        "difficulty": args.difficulty,
                        "build_mode": args.build_mode,
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
                ai_build=AIBuild[args.build_mode],
            )
            run_game(
                maps.get(args.map_name),
                [bot, opponent],
                realtime=False,
                save_replay_as=str(match_log_directory / "replay.SC2Replay"),
            )
        finally:
            logger.remove()


if __name__ == "__main__":
    main()
