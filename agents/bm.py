from agents.base import BaseAgent
from agents.prompts import construct_rules, strategy_prompt
from runtime.format import construct_ordered_list, extract_code

import json


def create_bm_prompt(
    race: str,
    obs_text: str,
    metrics: dict,
    actions: list | None = None,
    background_request: str = "",
):
    metrics_text = json.dumps(metrics, indent=2, ensure_ascii=False)
    actions_text = json.dumps(actions or [], indent=2, ensure_ascii=False)
    request_text = background_request.strip() or "[No specific background request]"
    rules_text = construct_ordered_list(construct_rules(race)[1:])

    return f"""
You are a StarCraft II background decision model. Your task is to provide guidance for the next period of play based on the current observation and the background request. Do not output executable StarCraft II actions.

### Aim
{strategy_prompt}

### Rules
{rules_text}

### Background Information
{metrics_text}

### Background Request
{request_text}

### Frozen Game State Before IM Actions
{obs_text}

### IM Validated Actions
{actions_text}

### Examples

Following are some examples:
- First accumulate resources;
- First respond to the current attack;
- Resources are scarce, open a new base;
- Continue producing attacking units;
- Search for and destroy remaining enemy structures;
- ...

Give concise high-level guidance as a JSON list of strings wrapped with triple backticks:
```
[
    "<guidance_1>",
    "<guidance_2>",
    ...
]
```
    """.strip()


class BmAgent(BaseAgent):
    def __init__(self, race: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.race = race
        self.think = []
        self.chat_history = []

    def _safe_parse(self, response: str) -> dict:
        try:
            payload = json.loads(extract_code(response))
            if isinstance(payload, list):
                guidance = [str(item) for item in payload]
            elif isinstance(payload, dict):
                raw_guidance = payload.get("guidance") or payload.get("directives") or payload.get("instructions")
                if isinstance(raw_guidance, list):
                    guidance = [str(item) for item in raw_guidance]
                else:
                    guidance = [str(value) for value in payload.values() if isinstance(value, str)]
            elif isinstance(payload, str):
                guidance = [payload]
            else:
                raise ValueError("BM response must be a JSON list, object, or string")
        except Exception:
            guidance = [
                "Continue with a safe baseline: keep economy active, avoid invalid repeated actions, and attack only with a clear advantage."
            ]

        guidance = [item.strip() for item in guidance if item and item.strip()]
        if not guidance:
            guidance = ["No specific background guidance is available; follow the current game state and strategic aim."]
        return {"guidance": guidance}

    def run(
        self,
        obs_text: str,
        metrics: dict,
        actions: list | None = None,
        background_request: str = "",
    ):
        self.think = []
        self.chat_history = []

        prompt = create_bm_prompt(
            race=self.race,
            obs_text=obs_text,
            metrics=metrics,
            actions=actions,
            background_request=background_request,
        )
        response, messages = self.llm_client.call(
            prompt=prompt,
            **self.generation_config,
            need_json=True,
        )
        self.think.append([response])
        self.chat_history.append(messages)

        directive = self._safe_parse(response)
        return directive, self.think, self.chat_history
