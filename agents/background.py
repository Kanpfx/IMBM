import json

from agents.base import BaseAgent
from agents.prompts.background import (
    construct_plan_example,
    construct_rules,
    create_plan_critic_prompt,
    create_plan_prompt,
)
from utils.format import construct_ordered_list, extract_code, json_to_markdown


class BmAgent(BaseAgent):
    """BM 负责在后台生成中期战略指令，不直接执行动作。"""

    def __init__(self, race, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.race = race
        self.rules = construct_rules(race)
        self.plan_example = construct_plan_example(race)

        self.max_refine_times = 2
        self.think = []
        self.chat_history = []
        self.last_trace = {"calls": [], "critics": []}

    def _safe_parse(self, response: str) -> list[str]:
        # BM 输出只需要能落成字符串列表；失败时给出保守默认战略。
        try:
            payload = json.loads(extract_code(response))
            if isinstance(payload, list):
                return [str(item).strip() for item in payload if str(item).strip()]
            elif isinstance(payload, dict):
                values = [v for v in payload.values() if isinstance(v, str) and v.strip()]
                return values if values else ["Continue current strategy."]
            elif isinstance(payload, str):
                return [payload.strip()]
        except Exception:
            pass
        return ["Maintain economy, produce units, and defend."]

    def gene_new_plan(self, obs_text: str, rules: list[str], background_request: str = ""):
        # 初始计划由当前真实观测、触发原因和建议规则共同决定。
        prompt = create_plan_prompt(self.race, rules, obs_text, background_request)
        response, messages = self.llm_client.call(**self.generation_config, prompt=prompt, need_json=True)
        self.last_trace["calls"].append({"stage": "plan", "prompt": prompt, "response": response})
        self.think.append([response])
        self.chat_history.append(messages)
        return json.loads(extract_code(response))

    def critic_plan(self, plan: list[str], obs_text: str, rules: list[str], round_number: int):
        # BM 自审只检查战略命令本身，不接触动作执行层。
        prompt = create_plan_critic_prompt(rules, obs_text, plan)
        response, messages = self.llm_client.call(**self.generation_config, prompt=prompt, need_json=True)
        self.last_trace["calls"].append(
            {"stage": f"critic_{round_number}", "prompt": prompt, "response": response}
        )
        self.think[-1].append(response)
        self.chat_history.append(messages)
        return response

    def refine_plan(
        self,
        obs_text: str,
        plan: list[str],
        critic: str,
        rules: list[str],
        background_request: str = "",
        round_number: int = 1,
    ):
        gene_prompt = create_plan_prompt(self.race, rules, obs_text, background_request)
        # 保留原计划上下文，让模型针对 critic 做局部修正。
        history = [
            {"role": "user", "content": gene_prompt},
            {"role": "assistant", "content": json_to_markdown(plan)},
        ]
        prompt = (
            "Errors:\n"
            + critic
            + "\nRethink with the given rules and errors step by step, and then give a refined plan based on the current game state."
        )
        response, messages = self.llm_client.call(**self.generation_config, prompt=prompt, history=history, need_json=True)
        self.last_trace["calls"].append(
            {"stage": f"refine_{round_number}", "prompt": prompt, "response": response}
        )
        self.think.append([response])
        self.chat_history.append(messages)
        return json.loads(extract_code(response))

    def refine_plan_until_ready(self, obs_text: str, plan: list[str], rules: list[str], background_request: str = ""):
        for round_number in range(1, self.max_refine_times + 1):
            critic = self.critic_plan(plan, obs_text, rules, round_number)
            critic = json.loads(extract_code(critic))
            if isinstance(critic, list):
                critic = {"error_number": len(critic), "errors": critic}
            self.last_trace["critics"].append(
                {
                    "round": round_number,
                    "error_number": critic.get("error_number", 0),
                    "errors": critic.get("errors", []),
                }
            )
            if critic.get("error_number", 0) == 0:
                return plan
            critic = construct_ordered_list(critic.get("errors", []))
            plan = self.refine_plan(
                obs_text,
                plan,
                critic,
                rules,
                background_request,
                round_number,
            )
        return plan

    def run(
        self,
        obs_text: str,
        background_request: str = "",
        suggestions: list[str] = [],
    ):
        self.think = []
        self.chat_history = []
        self.last_trace = {"calls": [], "critics": []}

        # 静态种族规则 + 当前建议一起约束 BM 的战略输出。
        rules = self.rules + suggestions
        plan = self.gene_new_plan(obs_text, rules, background_request)
        plan = self.refine_plan_until_ready(obs_text, plan, rules, background_request)

        return plan, self.think, self.chat_history
