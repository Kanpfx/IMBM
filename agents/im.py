from agents.base import BaseAgent
from runtime.format import extract_code, constrcut_openai_qa

import json


role_prompt = """
You are a real-time StarCraft II controller. Based on the current game state and the background model's guidance, choose immediately executable actions that help us win the game.
""".strip()


strategic_aim_prompt = """
Our final aim: defeat the enemy as efficiently as possible.

Our action preferences:
- Economy: maintain healthy resource income and spending.
- Infrastructure and tech: build structures and progress technology at appropriate timings.
- Army and combat: defend against enemy attacks when needed, and organize reasonable attacks with our army.
""".strip()


action_format_prompt = """
```
{
    "actions": [
        {
            "action": "<action_name>",
            "units": [1, 2],
            "target_unit": 3
        }
    ],
    "request_background": true,
    "background_reason": "<reason why we request updated background strategic guidance>"
}
```
""".strip()


action_example_prompt = """
Example:
```
{
  "actions": [
    {
      "action": "TERRANBUILD_SUPPLYDEPOT",
      "units": [1],
      "target_position": [24, 30]
    },
    {
      "action": "COMMANDCENTERTRAIN_SCV",
      "units": [2]
    }
  ],
  "request_background": true,
  "background_reason": "We are under heavy attack and need updated guidance on how to handle the next step."
}
```
""".strip()


action_rules_prompt = """
Immediate Action Rules:

1. Executability
- Only output actions that are currently available in the observation's Unit abilities or Structure abilities.
- Each unit or structure may receive at most one action in this response.
- Prefer actions that are useful immediately; ignore strategic ideas that cannot be executed now.

2. Balanced Control
- At every decision, consider survival, economy, supply, production, technology, scouting, and combat.
- Choose the actions with the highest immediate value across these areas, not only the most obvious combat or production action.
- Before finalizing actions, check whether any critical area has an urgent gap.

3. Economy And Spending
- Keep worker production healthy while it improves mining efficiency, but avoid excessive worker queues or over-saturating bases.
- Spend resources efficiently across workers, supply, production, tech, army, defenses, and expansions.
- When resources are floating, prefer actions that increase long-term capacity or convert resources into useful army strength.

4. Production And Tech
- Keep idle production structures active when resources and supply allow.
- Build or upgrade infrastructure when current production capacity, tech access, or army composition is limiting future strength.
- Do not repeatedly queue the same structure's production if its queue is already long; diversify spending when possible.

5. Supply And Expansion
- Prevent supply blocks before they stop production.
- Expand when the current economy is saturated or resource income limits the plan, unless there is an immediate threat that must be handled first.
- Do not delay expansion forever because of vague uncertainty; use the current threat level and army readiness to decide.

6. Combat And Information
- Defend important economy and production assets when threatened.
- Scout or move for information when enemy state is unknown and the cost is acceptable.
- Attack when the army is grouped and the expected trade is favorable; avoid feeding small groups unless scouting, harassing, or finishing a weak target.

7. Background Requests
- Request background guidance when there is strategic uncertainty: tech path, expansion timing, attack timing, enemy composition, or major plan changes.
- Do not request background guidance for local execution issues such as insufficient resources, full queues, invalid actions, or obvious defensive responses.
""".strip()


def create_im_prompt(race: str, obs_text: str, directive_text: str | None):
    directive_text = directive_text or "[No active directive]"
    return f"""
{role_prompt}

### Strategic Objective
{strategic_aim_prompt}

### Current Game State
{obs_text}

### Current Strategic Guidance
{directive_text}

### Immediate Action Rules
{action_rules_prompt}

### Required JSON Output
{action_format_prompt}

### Example JSON Output
{action_example_prompt}

Please output only the well-formed JSON object that you have decided on, wrapped with triple backticks, with no extra text.
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

    def run(self, obs_text: str, directive_text: str | None = None, verifier=None):
        self.think = []
        self.chat_history = []

        prompt = create_im_prompt(self.race, obs_text, directive_text)
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
