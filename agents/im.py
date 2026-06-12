from agents.base_agent import BaseAgent
from agents.common import format_prompt
from tools.format import extract_code, constrcut_openai_qa

import json


# ── Role ──
role_prompt = """
As a top-tier StarCraft II executor, your task is to give some actions to finish the given task as possible as you can. You must also predict the near-future game state and request strategic guidance from the background model when facing strategic uncertainty.
""".strip()


# ── Executor rules (from SunTzu action_agent, unchanged) ──
executor_rules = [
    "Do not give any action that is irrelevant to the task.",
    "Each of units can only be used in the whole response once at most.",
    "If a unit is already performing an action as given task, you should ignore it, instead of giving a repeated action for it.",
    "If one task cannot be finished, just ignore it.",
    "If resource is not enough, just complete the most important part of the task.",
]

# ── New IMBM rules ──
prediction_rule = (
    "Predicted Observation: write a formal observation snapshot predicting the game state ~30 ticks after "
    "executing your actions. It must contain all 10 section headers (# Round state, # Own units, # Unit abilities, "
    "# Own structures, # Structure abilities, # Visible enemy units, # Visible enemy structures, "
    "# Action history, # Map information, # Ability description). "
    "The prediction should reflect the consequences of your chosen actions (e.g. resources spent, units produced, structures started)."
)

background_request_rule = (
    "Background Request: set request_background=true ONLY when facing strategic uncertainty "
    "(unknown enemy strategy, major tech switch decision, expansion timing, army composition choices). "
    "Do NOT request for local execution issues (insufficient resources, placement blocked, unit busy). "
    "Provide a concrete background_reason describing what strategic question needs answering."
)

all_rules = executor_rules + [prediction_rule, background_request_rule]
rules_prompt = "Rule checklist:\n" + "\n".join([f"{i+1}. {rule}" for i, rule in enumerate(all_rules)])


# ── Output format ──
action_format_prompt = """
```
{
    "predicted_observation": "<formal observation snapshot about 30 ticks later, formatted like the input observation. Use escaped newline characters inside this JSON string.>",
    "actions": [
        {
            "action": "<action_name>",
            "units": [1, 2],
            "target_unit": 3
        }
    ],
    "request_background": true,
    "background_reason": "<reason why we request updated strategic tasks>"
}
```
""".strip()


action_example_prompt = """
Example:
```
{
  "predicted_observation": "# Round state\\nTime: about 30 ticks later\\nRace: Terran\\nMinerals: lower after starting the Supply Depot and SCV\\nVespene: unchanged or slightly higher from mining\\nSupply army: unchanged\\nSupply workers: unchanged until the queued SCV completes\\nSupply unused: lower while the SCV is queued, then improved as the Supply Depot progresses\\nMap size: unchanged\\n\\n# Own units\\nSCVs continue collecting resources automatically. The selected SCV starts constructing a Supply Depot near the base.\\n\\n# Unit abilities\\nAvailable worker abilities remain similar except the constructing SCV should not receive another command.\\n\\n# Own structures\\nCommand Center is training an SCV. Supply Depot is under construction near the base.\\n\\n# Structure abilities\\nCommand Center production is occupied by the SCV queue.\\n\\n# Visible enemy units\\n[Empty] unless new enemy units enter vision.\\n\\n# Visible enemy structures\\n[Empty] unless enemy structures enter vision.\\n\\n# Action history\\nIncludes TERRANBUILD_SUPPLYDEPOT and COMMANDCENTERTRAIN_SCV.\\n\\n# Map information\\nClosest mineral fields and vespene geysers remain unchanged.\\n\\n# Ability description\\nRelevant available ability descriptions remain consistent with the current observation.",
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
  "background_reason": "We are under heavy attack and need updated strategic tasks."
}
```
""".strip()


required_predicted_observation_sections = [
    "# Round state",
    "# Own units",
    "# Unit abilities",
    "# Own structures",
    "# Structure abilities",
    "# Visible enemy units",
    "# Visible enemy structures",
    "# Action history",
    "# Map information",
    "# Ability description",
]


# ── Prompt builder ──
def create_im_prompt(obs_text: str, plan_text: str | None):
    plan_section = plan_text or "[No active tasks — act based on the current game state]"
    return f"""
{role_prompt}

### Current Game State
{obs_text}

### Given Tasks
{plan_section}

### Rules
{rules_prompt}

### Required JSON Output
{action_format_prompt}

### Example JSON Output
{action_example_prompt}

Please output only the well-formed JSON object that you have decided on, wrapped with triple backticks, with no extra text.
    """.strip()


# ── ImAgent ──
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
                raise ValueError(
                    "IM response must be a JSON object with predicted_observation, actions, request_background, and background_reason."
                )
            if "predicted_observation" not in payload:
                raise ValueError("Missing required key: predicted_observation.")
            predicted_observation = payload["predicted_observation"]
            if isinstance(predicted_observation, (dict, list)):
                predicted_observation = json.dumps(predicted_observation, ensure_ascii=False)
            else:
                predicted_observation = str(predicted_observation)
            if not predicted_observation.strip():
                raise ValueError("`predicted_observation` must be a non-empty observation snapshot.")
            missing_sections = [
                section
                for section in required_predicted_observation_sections
                if section not in predicted_observation
            ]
            if missing_sections:
                raise ValueError(
                    "`predicted_observation` must be formatted as a formal observation snapshot. "
                    + "Missing sections: "
                    + ", ".join(missing_sections)
                )
            actions = payload.get("actions", [])
            if not isinstance(actions, list):
                raise ValueError("`actions` must be a list.")
            return {
                "predicted_observation": predicted_observation,
                "actions": actions,
                "request_background": bool(payload.get("request_background", False)),
                "background_reason": str(payload.get("background_reason", "")),
            }, ""
        except Exception as exc:
            return {
                "predicted_observation": "",
                "actions": [],
                "request_background": False,
                "background_reason": "",
            }, str(exc)

    def _safe_parse(self, response: str) -> dict:
        payload, error = self._parse_response(response)
        if error:
            return {
                "predicted_observation": "",
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

    def run(self, obs_text: str, plan_text: str | None = None, verifier=None):
        self.think = []
        self.chat_history = []

        prompt = create_im_prompt(obs_text, plan_text)
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
            payload["predicted_observation"],
            payload["actions"],
            payload["request_background"],
            payload["background_reason"],
            self.think,
            self.chat_history,
        )
