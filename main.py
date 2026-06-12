from sc2 import maps
from sc2.player import Bot, Computer
from sc2.main import run_game
from sc2.data import Race, Difficulty, AIBuild
from argparse import ArgumentParser
import json
import os

from config import game
from config.env import load_environment, require_env, build_generation_config
from core.player import ImBmPlayer
from tools.llm import LLMClient

load_environment()


def parse_args():
    parser = ArgumentParser()
    parser.add_argument(
        "--map_name",
        choices=game.map_choices,
        help="Map name",
        required=True,
    )
    parser.add_argument(
        "--difficulty",
        choices=game.difficulty_choices,
        help="Bot difficulty",
        required=True,
    )
    parser.add_argument(
        "--ai_build",
        choices=game.ai_build_choices,
        help="AI build",
        default="RandomBuild",
    )
    parser.add_argument(
        "--player_name",
        type=str,
        help="Player name",
        default="im_bm_player",
    )
    parser.add_argument(
        "--own_race",
        choices=game.race_choices,
        default="Terran",
    )
    parser.add_argument(
        "--enemy_race",
        choices=game.race_choices,
        default="Terran",
    )
    parser.add_argument(
        "-bm",
        action="store_true",
        help="Enable background model (BM) for async strategic planning",
    )
    parser.add_argument(
        "--enable_random_decision_interval",
        action="store_true",
        help="Randomize decision interval for data collection",
    )

    args = parser.parse_args()

    require_env(["IM_MODEL_NAME", "IM_BASE_URL", "IM_API_KEY"])
    if args.bm:
        require_env(["BM_MODEL_NAME", "BM_BASE_URL", "BM_API_KEY"])

    return args


def main():
    args = parse_args()

    im_model_name = os.getenv("IM_MODEL_NAME", "")
    bm_model_name = os.getenv("BM_MODEL_NAME", "")
    log_path = f"logs/{args.player_name}/{args.map_name}_{args.difficulty}_{args.ai_build}/im_bm"

    # ── IM LLM config (required) ──
    im_llm_config = {
        "model_name": im_model_name,
        "generation_config": build_generation_config(im_model_name),
        "llm_client": LLMClient(
            base_url=os.getenv("IM_BASE_URL", ""),
            api_key=os.getenv("IM_API_KEY", ""),
        ),
    }

    # ── BM LLM config (optional) ──
    bm_llm_config = {}
    if args.bm:
        bm_llm_config = {
            "bm_model_name": bm_model_name,
            "bm_generation_config": build_generation_config(bm_model_name),
            "bm_llm_client": LLMClient(
                base_url=os.getenv("BM_BASE_URL", ""),
                api_key=os.getenv("BM_API_KEY", ""),
            ),
        }

    # ── Players ──
    join_player = Computer(
        race=getattr(Race, args.enemy_race),
        difficulty=getattr(Difficulty, args.difficulty),
        ai_build=getattr(AIBuild, args.ai_build),
    )
    ai_player = ImBmPlayer(
        config=args,
        player_name=args.player_name,
        log_path=log_path,
        enable_bm=args.bm,
        **im_llm_config,
        **bm_llm_config,
    )
    host_player = Bot(getattr(Race, args.own_race), ai_player)

    # ── Save config for logging ──
    config_for_log = {
        "map_name": args.map_name,
        "difficulty": args.difficulty,
        "ai_build": args.ai_build,
        "player_name": args.player_name,
        "own_race": args.own_race,
        "enemy_race": args.enemy_race,
        "enable_bm": args.bm,
        "enable_random_decision_interval": args.enable_random_decision_interval,
        "im_model_name": im_model_name,
        "im_base_url": os.getenv("IM_BASE_URL", ""),
        "bm_model_name": bm_model_name if args.bm else "",
        "bm_base_url": os.getenv("BM_BASE_URL", "") if args.bm else "",
    }
    with open(ai_player.log_path + "/config.json", "w", encoding="utf-8") as f:
        json.dump(config_for_log, f, indent=4, ensure_ascii=False)

    run_game(
        maps.get(args.map_name),
        [host_player, join_player],
        realtime=False,
        rgb_render_config=None,
        save_replay_as=ai_player.log_path + "/replay.SC2Replay",
    )


if __name__ == "__main__":
    main()
