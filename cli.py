from argparse import ArgumentParser
import json
import os

from config import game
from config.env import load_environment, require_env, build_generation_config

load_environment()  # 入口启动时统一读取 .env，后续 IM/BM 配置都从环境变量取。


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
        "--bm",
        action="store_true",
        help="Enable background model (BM) for async strategic planning",
    )
    parser.add_argument(
        "-observation",
        "--observation",
        action="store_true",
        help="Ask IM to include predicted_observation in its JSON output",
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

    from sc2 import maps
    from sc2.data import AIBuild, Difficulty, Race
    from sc2.main import run_game
    from sc2.player import Bot, Computer

    from player import ImBmPlayer
    from utils.llm import LLMClient

    im_model_name = os.getenv("IM_MODEL_NAME", "")
    bm_model_name = os.getenv("BM_MODEL_NAME", "")
    log_path = f"logs/{args.player_name}/{args.map_name}_{args.difficulty}_{args.ai_build}/im_bm"

    # IM 是主决策模型，必须配置。
    im_llm_config = {
        "model_name": im_model_name,
        "generation_config": build_generation_config(im_model_name),
        "llm_client": LLMClient(
            base_url=os.getenv("IM_BASE_URL", ""),
            api_key=os.getenv("IM_API_KEY", ""),
        ),
    }

    # BM 只在 --bm 打开时创建，避免单模型运行时强依赖 BM 环境变量。
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

    # python-sc2 需要分别构造我方 Bot 和敌方内置 AI。
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

    # 保存本局实验配置，便于之后按日志复现实验条件。
    config_for_log = {
        "map_name": args.map_name,
        "difficulty": args.difficulty,
        "ai_build": args.ai_build,
        "player_name": args.player_name,
        "own_race": args.own_race,
        "enemy_race": args.enemy_race,
        "enable_bm": args.bm,
        "enable_observation": args.observation,
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
