from agents.base import BaseAgent
from runtime.format import extract_code

import json


role_prompt = """
You are a strong background decision model for StarCraft II. Based on the current observation and request, provide macro-level guidance for the next period of the game, covering multiple steps and aspects of play. Give strategic advice, not executable actions.
""".strip()


strategic_aim_prompt = """
Our overall goal: strategically coordinate resources, army strength, technology, and development to ultimately defeat the enemy.

Strategic decision preferences:
- Resources: maintain efficient resource income and healthy resource usage.
- Development: plan technology progression and organize effective development.
- Combat: allocate army forces reasonably to defend against attacks and win favorable fights.
""".strip()


guidance_rules_prompt = """
Guidance Rules:

1. Overall Requirements
- You are a high-level command agent. Output only natural-language strategic guidance, not concrete executable actions.
- Based on the current observation, IM request, resources, buildings, army strength, and enemy threats, plan the resource, construction, technology, and combat direction for roughly the next minute.
- When the IM makes a request, prioritize answering that request, then add corrections or supplements based on the global situation.
- Guidance should express goals, priorities, and tactical intent. Do not specify exact unit IDs, coordinates, quantities, or operation sequences.

2. Resource Requirements
- Avoid long-term resource floating. Continuously convert minerals and gas into economy, production, technology, or army strength.
- When resources are insufficient, prioritize restoring income and keeping key production active.
- When resources are severely imbalanced, adjust collection and spending priorities.
- When minerals are excessive, prefer expansion, additional production, basic army units, or defense.
- When gas is excessive, prefer technology progression, upgrades, or higher-tech units.

3. Construction Requirements
- Expand when the environment is safe and resources allow it, but do not expand blindly.
- When production capacity is insufficient, add the corresponding production structures or add-ons.
- Technology progression should serve the current unit route and enemy threats. Do not make purposeless tech switches.
- Defensive structures should protect key areas such as mineral lines, entrances, and expansions.

4. Combat Requirements
- Small harassment is usually handled by the IM locally; only provide high-level defensive priorities.
- When facing a large attack, prioritize gathering the main army, defending key areas, and protecting economy and production structures.
- When we gain an army, economy, or technology advantage, organize grouped attacks to pressure enemy expansions or damage the enemy economy.
- Before attacking, consider scouting information, army readiness, key technology, and enemy defensive strength.

5. Scouting Requirements
- When enemy information is insufficient, prioritize scouting or scanning before making aggressive judgments.
- Adjust attack timing, unit route, and technology tree based on enemy expansion, unit composition, and technology information.
""".strip()


guidance_format_prompt = """
```
[
    "<guidance_1>",
    "<guidance_2>",
    ...
]
```
""".strip()


guidance_example_prompt = """
Examples:
- Resource Guidance: Gas is excessive; reduce gas collection and spend more gas on technology, upgrades, or high-tech units.
- Combat Guidance: Gather army forces to respond to this attack.
- Construction Guidance: It is safe and reasonable to open a new base.
""".strip()


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

    return f"""
{role_prompt}

### Aim
{strategic_aim_prompt}

### Rules
{guidance_rules_prompt}

### Background Information
{metrics_text}

### Background Request
{request_text}

### Frozen Game State Before IM Actions
{obs_text}

### IM Validated Actions
{actions_text}

### Examples
{guidance_example_prompt}

Give concise high-level guidance as a JSON list of strings wrapped with triple backticks:
{guidance_format_prompt}
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
