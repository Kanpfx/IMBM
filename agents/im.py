from agents.base import BaseAgent
from runtime.action_queue import QUEUE_NAMES
from runtime.format import extract_code, constrcut_openai_qa

import json


role_prompt = """
You are a StarCraft II decision executor. Based on the current observation and the given queue task, produce concrete executable actions for the agent.
""".strip()


queue_aims = {
    "economy_build": "Core Aim: Execute the current economy or building task with available workers, bases, structures, and valid build or economy abilities.",
    "production_tech": "Core Aim: Execute the current production or technology task with available production structures, tech structures, add-ons, and research or training abilities.",
    "combat": "Core Aim: Execute the current combat task with available combat units, visible targets, map positions, and valid movement, attack, defense, scouting, or combat abilities.",
}


queue_templates = {
    "economy_build": """
Queue Template: economy_build
- Use only economy, worker, base, supply, building, and base-upgrade abilities shown in the filtered ability table.
- Choose valid builders, producers, targets, and building positions from the observation.
- Prefer actions that improve income, supply capacity, bases, or infrastructure.
""".strip(),
    "production_tech": """
Queue Template: production_tech
- Use only army production, research, upgrade, add-on, and tech morph abilities shown in the filtered ability table.
- Choose idle or suitable production/tech structures from the observation.
- Prefer actions that turn resources into useful army strength or unlock the next coherent tech step.
""".strip(),
    "combat": """
Queue Template: combat
- Use only movement, attack, defense, scouting, combat abilities, and combat mode abilities shown in the filtered ability table.
- Choose combat units and visible enemy units or map positions from the observation.
- Prefer useful immediate combat behavior: defend, regroup, scout, attack favorable targets, or use safe combat abilities.
""".strip(),
}


action_rules_prompt = """
Immediate Execution Rules:
- Only output actions that are currently available in the filtered Unit abilities or Structure abilities.
- Each unit or structure may receive at most one action in this response.
- If the task cannot be executed now, output an empty actions list.
- Do not invent unit ids, ability names, enemy ids, or coordinates outside the observation.
- Return only low-level SC2 action JSON. Do not explain.
""".strip()


action_format_prompt = """
```
{
  "actions": [
    {
      "action": "<no_target_action_name>",
      "units": [1]
    },
    {
      "action": "<unit_target_action_name>",
      "units": [1],
      "target_unit": 2
    },
    {
      "action": "<point_target_action_name>",
      "units": [1],
      "target_position": [40, 24]
    }
  ]
}
```
""".strip()


queue_example_results = {
    "economy_build": """
```
{
  "actions": [
    {
      "action": "COMMANDCENTERTRAIN_SCV",
      "units": [377]
    }
  ]
}
```
""".strip(),
    "production_tech": """
```
{
  "actions": [
    {
      "action": "BARRACKSTRAIN_MARINE",
      "units": [12]
    }
  ]
}
```
""".strip(),
    "combat": """
```
{
  "actions": [
    {
      "action": "MOVE_MOVE",
      "units": [105],
      "target_position": [40, 24]
    }
  ]
}
```
""".strip(),
}


def create_im_prompt(race: str, queue_name: str, obs_text: str, task: dict):
    queue_aim = queue_aims.get(queue_name, "")
    template = queue_templates.get(queue_name, "")
    example_result = queue_example_results.get(queue_name, "")
    task_text = json.dumps(task, indent=2, ensure_ascii=False)
    return f"""
{role_prompt}

# Task Aim
{queue_aim}

# Current Observation
{obs_text}

# Current Task
{task_text}

# Task Guidance
{template}

# Rules
{action_rules_prompt}

# Required JSON Output
{action_format_prompt}

# Example
{example_result}

Please output only the JSON object wrapped with triple backticks, with no extra text.
    """.strip()


class ImAgent(BaseAgent):
    def __init__(self, race: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.race = race
        self.max_retry_attempts = 3
        self.think = []
        self.chat_history = []

    def _parse_response(self, response: str) -> tuple[list, str]:
        try:
            code = extract_code(response)
            if not code:
                raise ValueError("Response must contain a JSON code block wrapped with triple backticks.")
            payload = json.loads(code)
            if not isinstance(payload, dict):
                raise ValueError("IM response must be a JSON object with an actions list.")
            actions = payload.get("actions", [])
            if not isinstance(actions, list):
                raise ValueError("`actions` must be a list.")
            return actions, ""
        except Exception as exc:
            return [], str(exc)

    def _refine_schema_prompt(self, error: str) -> str:
        return (
            "The previous IM response failed JSON syntax/schema validation:\n"
            + error
            + "\nReturn only a JSON object wrapped with triple backticks in this schema:\n"
            + action_format_prompt
        )

    def _refine_actions_prompt(self, verification_message: str) -> str:
        return (
            "The previous IM actions failed validation:\n"
            + verification_message
            + "\nReturn only a refined JSON object wrapped with triple backticks in this schema. If the task cannot be executed now, use an empty actions list:\n"
            + action_format_prompt
        )

    def run(self, queue_name: str, obs_text: str, task: dict, verifier=None):
        if queue_name not in QUEUE_NAMES:
            return [], [[f"Unknown queue: {queue_name}"]], []

        self.think = []
        self.chat_history = []

        prompt = create_im_prompt(self.race, queue_name, obs_text, task)
        response, messages = self.llm_client.call(
            prompt=prompt,
            **self.generation_config,
            need_json=True,
        )
        self.think.append([response])
        self.chat_history.append(messages)

        history = constrcut_openai_qa(prompt, response)
        actions, parse_error = self._parse_response(response)

        for _ in range(self.max_retry_attempts):
            if parse_error:
                self.think[-1].append(parse_error)
                refine_prompt = self._refine_schema_prompt(parse_error)
                response, messages = self.llm_client.call(
                    prompt=refine_prompt,
                    history=history,
                    **self.generation_config,
                    need_json=True,
                )
                self.think.append([response])
                self.chat_history.append(messages)
                history.extend(constrcut_openai_qa(refine_prompt, response))
                actions, parse_error = self._parse_response(response)
                continue

            if not verifier:
                break

            ok, verification_message = verifier(actions)
            self.think[-1].append(verification_message)
            if ok:
                break

            refine_prompt = self._refine_actions_prompt(verification_message)
            response, messages = self.llm_client.call(
                prompt=refine_prompt,
                history=history,
                **self.generation_config,
                need_json=True,
            )
            self.think.append([response])
            self.chat_history.append(messages)
            history.extend(constrcut_openai_qa(refine_prompt, response))
            actions, parse_error = self._parse_response(response)

        actions, _ = self._parse_response(response)
        return actions, self.think, self.chat_history
