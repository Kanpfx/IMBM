from agents.base import BaseAgent
from runtime.format import extract_code

import json


role_prompt = """
You are a strong background decision model for StarCraft II. Based on the current observation and request, provide macro-level guidance for the next period of the game, covering multiple steps and aspects of play. Give strategic advice, not executable actions.
""".strip()


strategic_aim_prompt = """
Our overall goal: strategically coordinate economy, production infrastructure, technology, and army strength to ultimately defeat the enemy.

Strategic decision preferences:
- Economy: maintain efficient resource income and healthy resource spending.
- Infrastructure and tech: plan production structures, add-ons, upgrades, and technology progression.
- Army and combat: allocate army forces reasonably to defend against attacks and win favorable fights.
""".strip()


guidance_rules_prompt = """
Strategic Guidance Rules:

1. Strategic Scope Rules
- You are a high-level command agent. Output only natural-language strategic guidance, not concrete executable actions.
- Based on the current observation, request, economy, production infrastructure, army strength, and enemy threats, plan the strategic direction for roughly the next minute.
- When the IM makes a request, prioritize answering that request, then add corrections or supplements based on the global situation.
- Guidance should express goals, priorities, and tactical intent. Do not specify exact unit IDs, coordinates, quantities, or operation sequences.

2. Economy Guidance Rules
- Avoid long-term resource floating. Continuously convert minerals and gas into economy, production, technology, or army strength.
- When resources are insufficient, prioritize restoring income and keeping key production active.
- When resources are severely imbalanced, adjust resource spending and economy priorities.
- When minerals are excessive, prefer expansion, additional production, basic army units, or defense.
- When gas is excessive, prefer technology progression, upgrades, or higher-tech units.

3. Construction and Tech Guidance Rules
- Expand when the environment is safe and resources allow it, but do not expand blindly.
- When production capacity is insufficient, add the corresponding production structures or add-ons.
- Technology progression should serve the current unit route and enemy threats. Do not make purposeless tech switches.
- Defensive structures should protect key areas such as mineral lines, entrances, and expansions.

4. Army and Combat Guidance Rules
- Small harassment is usually handled by the IM locally; only provide high-level defensive priorities.
- When facing a large attack, prioritize gathering the main army, defending key areas, and protecting economy and production structures.
- When we gain an army, economy, or technology advantage, organize grouped attacks to pressure enemy expansions or damage the enemy economy.
- Before attacking, consider scouting information, army readiness, key technology, and enemy defensive strength.

5. Scouting and Information Guidance Rules
- When enemy information is insufficient, prioritize scouting or scanning before making aggressive judgments.
- Adjust attack timing, unit route, and technology tree based on enemy expansion, unit composition, and technology information.

6. Directive Format Rules
- Output a JSON object with overall, resource, construction, and combat fields.
- overall is required; resource, construction, and combat are optional.
- Each included field must be one concise sentence.
""".strip()


guidance_format_prompt = """
```
{
    "overall": "<main strategic plan for the next period>",
    "resource": "<optional economy, workers, expansion, resource income, or resource-spending guidance>",
    "construction": "<optional buildings, production structures, add-ons, tech path, or upgrade guidance>",
    "combat": "<optional defense, attack timing, scouting, army posture, or unit-composition guidance>"
}
```
""".strip()


guidance_example_prompt = """
Example:
```
{
  "overall": "Defend with Marines and Tank tech first, then expand once the front is stable.",
  "resource": "Spend the mineral bank on worker production, army production, and a safe natural expansion.",
  "construction": "Prioritize Factory Tech Lab and Siege Tanks before adding unrelated tech.",
  "combat": "Hold near the bunker and wall until Tank support is ready, then look for a cautious pressure timing."
}
```
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

### Strategic Objective
{strategic_aim_prompt}

### Strategic Guidance Rules
{guidance_rules_prompt}

### Runtime Metrics
{metrics_text}

### Strategic Guidance Request
{request_text}

### Game State Snapshot Before IM Actions
{obs_text}

### IM Validated Actions
{actions_text}

### Example Directive JSON
{guidance_example_prompt}

### Required Directive JSON
{guidance_format_prompt}

Please output only the well-formed JSON object that you have decided on, wrapped with triple backticks, with no extra text.
    """.strip()


class BmAgent(BaseAgent):
    def __init__(self, race: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.race = race
        self.think = []
        self.chat_history = []

    def _safe_parse(self, response: str) -> dict:
        allowed_fields = ["overall", "resource", "construction", "combat"]
        try:
            payload = json.loads(extract_code(response))
            if isinstance(payload, list):
                directive = {"overall": " ".join(str(item).strip() for item in payload if str(item).strip())}
            elif isinstance(payload, dict):
                directive = {
                    field: payload[field].strip()
                    for field in allowed_fields
                    if isinstance(payload.get(field), str) and payload[field].strip()
                }
                raw_guidance = payload.get("guidance") or payload.get("directives") or payload.get("instructions")
                if isinstance(raw_guidance, list):
                    directive.setdefault(
                        "overall",
                        " ".join(str(item).strip() for item in raw_guidance if str(item).strip()),
                    )
            elif isinstance(payload, str):
                directive = {"overall": payload.strip()}
            else:
                raise ValueError("BM response must be a JSON object, list, or string")
        except Exception:
            directive = {
                "overall": "Continue with a safe baseline: keep economy active, avoid invalid repeated actions, and attack only with a clear advantage."
            }

        if not directive.get("overall"):
            directive["overall"] = "No specific background guidance is available; follow the current game state and strategic aim."
        return directive

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
