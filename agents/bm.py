from agents.base import BaseAgent
from runtime.action_queue import QUEUE_NAMES, WAITING
from runtime.format import extract_code

import json


role_prompt = """
You are an expert StarCraft II strategic decision model responsible for maintaining the agent's action queues. Given the current observation and existing queues, append a concise sequence of feasible near-term tasks that advances a planned, efficient path toward defeating the opponent.
""".strip()


queue_responsibility_prompt = """
Queue Responsibilities:

- economy_build: Maintain healthy resource income and spending, avoid supply or worker bottlenecks, expand when appropriate, and construct useful economic or infrastructure buildings.
- production_tech: Plan army production, add-ons, tech progression, upgrades, and unit composition so resources turn into coherent fighting strength.
- combat: Plan defense, scouting, regrouping, harassment, attacks, retreats, and combat ability usage according to enemy threats and army readiness.
""".strip()


guidance_rules_prompt = """
Strategic Guidance Rules:

1. Overall Responsibility
- Read the observation, metrics, existing queues, and blocked feedback before appending any task.
- Identify the most urgent short-term bottleneck: economy, supply, production, tech, defense, scouting, or attack timing.
- Keep the game plan balanced; do not improve one area while leaving another critical area stalled.
- If under pressure, prioritize survival, worker protection, base defense, and recovery.
- If safe, prioritize efficient resource spending, production growth, expansion, or useful technology.

2. economy_build Rules
- Maintain healthy resource income through workers, bases, gas access, and appropriate expansion timing.
- Prevent basic macro failures such as supply blocks, missing workers, idle economy, or delayed core infrastructure.
- Add buildings that support the current plan, such as supply, resource, production-enabling, tech-enabling, or static defense structures.
- Avoid redundant economy tasks when resources, workers, or bases are already sufficient for the current stage.

3. production_tech Rules
- Convert available minerals, gas, and production capacity into a coherent army composition.
- Add unit production tasks that fit current tech, enemy information, and the intended fighting plan.
- Add upgrades, add-ons, morphs, or tech progression when they directly improve future combat strength.
- Prefer consistent production plans over scattered unit choices or unsupported tech switches.

4. combat Rules
- Protect workers, bases, production structures, and key army units when enemy pressure is visible or likely.
- Scout when enemy information is poor before committing to risky tech choices or attacks.
- Regroup or defend when the army is fragmented, damaged, outnumbered, or poorly positioned.
- Harass or attack only when army readiness, enemy position, and tactical risk make the action reasonable.

5. Queue Requirements
- Only append new tasks; never delete, move, reorder, or rewrite existing queue items.
- Keep each queue compact, usually around 3 useful waiting tasks, and append nothing to queues that are already healthy.
- Avoid repeating existing tasks or recently blocked tasks unless the replacement is more specific and more executable.
- Each task must be one concise natural-language sentence, not a low-level ability name, unit id, or exact coordinate.
- If the queues already cover the next useful steps, output an empty append list.
""".strip()


output_format_prompt = """
```
{
  "append": [
    {
      "queue": "economy_build/production_tech/combat",
      "task": "The task to insert into the corresponding action queue."
    }
  ]
}
```
""".strip()


example_result = """
```
{
  "append": [
    {
      "queue": "economy_build",
      "task": "Stabilize the early economy by keeping worker production active and adding supply before a block."
    },
    {
      "queue": "production_tech",
      "task": "Begin basic infantry production from available Barracks to convert minerals into early army strength."
    },
    {
      "queue": "combat",
      "task": "Send a safe scout toward the opponent side of the map to identify the enemy opening without risking the economy."
    }
  ]
}
```
""".strip()


def create_bm_prompt(
    race: str,
    obs_text: str,
    metrics: dict,
    action_queues: dict,
    blocked_feedback: list | None = None,
):
    metrics_text = json.dumps(metrics, indent=2, ensure_ascii=False)
    queues_text = json.dumps(action_queues, indent=2, ensure_ascii=False)
    feedback_text = json.dumps(blocked_feedback or [], indent=2, ensure_ascii=False)

    return f"""
{role_prompt}

# Queue Responsibilities
{queue_responsibility_prompt}

# Current Observation
{obs_text}

# Current Action Queues
{queues_text}

# Blocked Task Feedback
{feedback_text}

# Strategic Guidance Rules
{guidance_rules_prompt}

# Required JSON Output
{output_format_prompt}

# Example
{example_result}

Please output only the JSON object wrapped with triple backticks, with no extra text.
    """.strip()


class BmAgent(BaseAgent):
    def __init__(self, race: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.race = race
        self.think = []
        self.chat_history = []

    def _safe_parse(self, response: str) -> list:
        try:
            payload = json.loads(extract_code(response))
        except Exception:
            return []
        if not isinstance(payload, dict):
            return []

        accepted = []
        append_items = payload.get("append", [])
        if not isinstance(append_items, list):
            return []

        for item in append_items:
            if not isinstance(item, dict):
                continue
            queue_name = item.get("queue")
            status = item.get("status", WAITING)
            task = item.get("task")
            if queue_name not in QUEUE_NAMES:
                continue
            if status != WAITING:
                continue
            if not isinstance(task, str) or not task.strip():
                continue
            accepted.append(
                {
                    "queue": queue_name,
                    "status": WAITING,
                    "task": task.strip(),
                }
            )
        return accepted

    def run(
        self,
        obs_text: str,
        metrics: dict,
        action_queues: dict,
        blocked_feedback: list | None = None,
    ):
        self.think = []
        self.chat_history = []

        prompt = create_bm_prompt(
            race=self.race,
            obs_text=obs_text,
            metrics=metrics,
            action_queues=action_queues,
            blocked_feedback=blocked_feedback,
        )
        response, messages = self.llm_client.call(
            prompt=prompt,
            **self.generation_config,
            need_json=True,
        )
        self.think.append([response])
        self.chat_history.append(messages)

        append_items = self._safe_parse(response)
        return append_items, self.think, self.chat_history
