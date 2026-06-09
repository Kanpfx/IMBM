from agents.base import BaseAgent
from runtime.action_queue import QUEUE_NAMES, WAITING
from runtime.format import extract_code

import json


role_prompt = """
后台计划器，负责全局决策与长期协调。
You maintain three high-level action queues for a StarCraft II agent. Read the observation and current queues, then append a small number of useful tasks.
""".strip()


queue_rules_prompt = """
Queue Rules:

1. Queues
- economy_build: economy, workers, bases, supply, buildings, and economy/base upgrades.
- production_tech: army production, research, upgrades, add-ons, and tech morphs.
- combat: movement, attacks, defense, scouting, combat abilities, and combat mode switches.

2. Work
- Only append new tasks. Do not delete, move, reorder, or rewrite existing tasks.
- Keep each queue around 5 tasks. If a queue is already near 5 useful tasks, append few or no tasks to it.
- Do not output low-level SC2 ability names, unit ids, or target coordinates.
- Each task must be one concise sentence.
- Prefer tasks that are actionable soon and fit the current game state.

3. Status
- Every appended task must use status "waiting".
""".strip()


output_format_prompt = """
```
{
  "append": [
    {
      "queue": "economy_build",
      "status": "waiting",
      "task": "Build a Supply Depot soon to avoid a supply block."
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

### Current Race
{race}

### Runtime Metrics
{metrics_text}

### Current Observation
{obs_text}

### Current Action Queues
{queues_text}

### Blocked Task Feedback
{feedback_text}

### Queue Rules
{queue_rules_prompt}

### Required JSON Output
{output_format_prompt}

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
            status = item.get("status")
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
