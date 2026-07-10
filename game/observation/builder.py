from knowledge.abilities import get_ability_desc
from game.observation.abilities import abilities_to_text
from game.observation.map_info import action_history_to_text, gas_to_text, miner_to_text, round_state_to_text
from game.observation.units import structures_to_text, units_to_text


async def build_observation_text(player):
    # 各段标题保持稳定，方便 prompt 和可选 predicted_observation 校验复用。
    obs = {}
    obs["Round state"] = round_state_to_text(player)
    obs["Own units"] = await units_to_text(player, player.units)
    obs["Unit abilities"] = await abilities_to_text(player, player.units)
    obs["Own structures"] = await structures_to_text(player, player.structures)
    obs["Structure abilities"] = await abilities_to_text(player, player.structures)
    obs["Visible enemy units"] = await units_to_text(player, player.enemy_units)
    obs["Visible enemy structures"] = await structures_to_text(player, player.enemy_structures)
    obs["Action history"] = action_history_to_text(player)
    obs["Map information"] = miner_to_text(player) + "\n" + gas_to_text(player)
    # 只补充当前观测中真正出现的 ability 描述，控制 prompt 长度。
    obs["Ability description"] = get_ability_desc(player, obs["Unit abilities"] + obs["Structure abilities"])
    obs_text = "\n\n".join([f"# {key}\n{value}" for key, value in obs.items()])

    player.logging("obs", obs, save_trace=True, print_log=False)
    if player.enable_logging:
        # 完整观测单独落盘，trace 里保存结构化版本。
        player.logging("obs_text", obs_text, save_file=True, print_log=False)
    return obs_text
