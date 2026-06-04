from agents.base import BaseAgent
from agents.prompts import strategy_prompt
from runtime.format import extract_code, constrcut_openai_qa

import json


role_prompt = """
You are a real-time StarCraft II controller. Based on the current game state and the background model's guidance, choose immediately executable actions that help us win the game.
""".strip()


action_format_prompt = """
```
{
    "actions": [
        {
            "action": "<action_name>",
            "units": [<unit_id>, <unit_id>, ...], # units you want to command
            "target_unit" (optional): <unit_id>, # some existing unit
            "target_position" (optional): [x, y]
        },
        // more actions ...
    ],
    "request_background": true/false, # whether a new background strategic analysis is needed
    "background_reason": "<reason>" # short reason when request_background is true, otherwise empty string
}
```
""".strip()


action_example_prompt = """
Example:
```
{
  "actions": [
    {
      "action": "ATTACK_ATTACK",
      "units": [1, 2, 3],
      "target_unit": 9
    },
    {
      "action": "MOVE_MOVE",
      "units": [4, 5],
      "target_position": [50, 60]
    },
    {
      "action": "COMMANDCENTERTRAIN_SCV",
      "units": [6]
    }
  ],
  "request_background": true,
  "background_reason": "We are under heavy attack and need updated background strategic guidance."
}
```
""".strip()


action_rules_prompt = """
Action Rules:

1. Overall Action Requirements
- Only output actions that are valid, supported, executable, and relevant to the current task.
- Ignore impossible tasks.
- Do not assign the same unit more than once in the same response.
- Avoid reassigning busy units unless the new command is clearly more urgent or useful.

2. Resource Requirements
- The total cost of all commands must not exceed available minerals and gas.
- If resources are insufficient, keep only the highest-priority commands.
- Do not manually send SCVs or MULEs to gather resources.
- Do not overproduce SCVs beyond useful Command Center and Refinery capacity.

3. Unit Production Requirements
- Prioritize increasing useful combat strength.
- Produce combat units that improve the current army within available resources and production capacity.
- Do not enqueue units if the production queue already contains 5 items.

4. Construction Requirements
- Build only structures that are currently useful.
- Avoid redundant structures.
- Do not build extra Refineries unless existing Refineries are fully utilized.
- Do not build Missile Turrets unless enemy air threats exist or are expected.
- Build at most one Supply Depot, and only when unused supply is below 7.

5. Background Strategy Requirements
- Follow background strategic guidance only if it is valid and reasonable under the current game state.
- When the situation requires long-term planning or strategic judgment, set request_background=true and provide a clear background_reason.
""".strip()


def create_im_prompt(race: str, obs_text: str, directive: dict | None):
    if directive is None:
        directive_text = "[No active directive]"
    else:
        directive_text = json.dumps(directive, indent=2, ensure_ascii=False)

    return f"""
{role_prompt}

### Aim
{strategy_prompt}

### Current Game State
{obs_text}

### Background Strategic Analysis
{directive_text}

### Rules
{action_rules_prompt}

Give an action JSON in the following format wrapped with triple backticks:
{action_format_prompt}

{action_example_prompt}
    """.strip()


class ImAgent(BaseAgent):
    def __init__(self, race: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.race = race
        self.max_retry_attempts = 3
        self.think = []
        self.chat_history = []

    def _parse_response(self, response: str) -> tuple[dict, str]:
        try:
            code = extract_code(response)
            if not code:
                raise ValueError("Response must contain a JSON code block wrapped with triple backticks.")
            payload = json.loads(code)
            if not isinstance(payload, dict):
                raise ValueError("IM response must be a JSON object with actions, request_background, and background_reason.")
            actions = payload.get("actions", [])
            if not isinstance(actions, list):
                raise ValueError("`actions` must be a list.")
            return {
                "actions": actions,
                "request_background": bool(payload.get("request_background", False)),
                "background_reason": str(payload.get("background_reason", "")),
            }, ""
        except Exception as exc:
            return {
                "actions": [],
                "request_background": False,
                "background_reason": "",
            }, str(exc)

    def _safe_parse(self, response: str) -> dict:
        payload, error = self._parse_response(response)
        if error:
            return {
                "actions": [],
                "request_background": True,
                "background_reason": "IM response could not be parsed.",
            }
        return payload

    def _refine_schema_prompt(self, error: str) -> str:
        return (
            "The previous IM response failed JSON syntax/schema validation:\n"
            + error
            + "\nReturn only a complete IM JSON object wrapped with triple backticks in this schema:\n"
            + action_format_prompt
        )

    def _refine_actions_prompt(self, verification_message: str) -> str:
        return (
            "The previous IM actions failed validation:\n"
            + verification_message
            + "\nAnalyze the issue silently and return only a complete refined IM JSON object wrapped with triple backticks in this schema:\n"
            + action_format_prompt
        )

    def run(self, obs_text: str, directive: dict | None = None, verifier=None):
        self.think = []
        self.chat_history = []

        prompt = create_im_prompt(self.race, obs_text, directive)
        response, messages = self.llm_client.call(
            prompt=prompt,
            **self.generation_config,
            need_json=True,
        )
        self.think.append([response])
        self.chat_history.append(messages)

        history = constrcut_openai_qa(prompt, response)
        payload, parse_error = self._parse_response(response)
        requested_background = payload["request_background"]
        requested_reason = payload["background_reason"]

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
                payload, parse_error = self._parse_response(response)
                if payload["request_background"]:
                    requested_background = True
                    requested_reason = payload["background_reason"] or requested_reason
                continue

            if not verifier:
                break

            ok, verification_message = verifier(payload["actions"])
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
            payload, parse_error = self._parse_response(response)
            if payload["request_background"]:
                requested_background = True
                requested_reason = payload["background_reason"] or requested_reason

        payload = self._safe_parse(response)
        if requested_background:
            payload["request_background"] = True
            payload["background_reason"] = payload["background_reason"] or requested_reason
        return (
            payload["actions"],
            payload["request_background"],
            payload["background_reason"],
            self.think,
            self.chat_history,
        )
