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

1. Role
- Provide strategic guidance for roughly the next minute of play.
- Give priorities, tradeoffs, and trigger conditions, not exact unit IDs or low-level command sequences.
- Guidance must respect the currently observed economy, army, tech, enemy information, and available action space.
- Before the directive fields, predict the likely observation about 30 ticks later after the IM actions and automatic economy/micro have progressed.
- Write the prediction as concise text with Economy, Production/Construction, Combat/Enemy, and Risk; do not copy the raw observation format or invent exact unit ids.

2. Strategic Balance
- Evaluate economy, supply, production capacity, technology, scouting, defense, and attack potential.
- Identify which area is currently the main bottleneck.
- Do not optimize only one dimension; a good plan should keep the overall game state growing.

3. Adaptation
- If under threat, prioritize survival, defense, and preserving economy.
- If safe and saturated, prioritize expansion or production growth.
- If resources are imbalanced, guide spending toward the area that converts the surplus into useful strength.
- If enemy information is poor, guide scouting before committing to a risky attack or tech switch.

4. Tech And Composition
- Recommend tech and unit composition based on our current infrastructure, resource balance, and enemy threats.
- Prefer coherent army plans over scattered unit choices.

5. Combat Posture
- Specify whether IM should defend, scout, regroup, contain, harass, or commit to an attack.
- For attacks, state the readiness condition or timing logic.
- For defense, state what must be protected and what kind of force posture is needed.

6. Directive Format
- Output concise JSON with predicted_observation_30_ticks, overall, priority, economy, construction, combat, and avoid fields.
- Each field should be one short sentence.
""".strip()


guidance_format_prompt = """
```
{
    "predicted_observation_30_ticks": "<brief text prediction for about 30 ticks later; summarize Economy, Production/Construction, Combat/Enemy, and Risk without copying the raw observation format>",
    "overall": "<main strategic plan for the next period>",
    "priority": "<the single most important bottleneck or objective now>",
    "economy": "<worker, saturation, expansion, supply, or spending guidance>",
    "construction": "<production, tech, add-ons, upgrades, or defense guidance>",
    "combat": "<defend, scout, regroup, attack, or timing guidance>",
    "avoid": "<one thing IM should not do in the next period>"
}
```
""".strip()


guidance_example_prompt = """
Example:
```
{
  "predicted_observation_30_ticks": "Economy: mining continues while current production spends minerals and gas. Production/Construction: Barracks production continues and Factory tech becomes the next likely bottleneck. Combat/Enemy: no immediate fight should change unless enemy pressure appears. Risk: pushing before the army is grouped would waste early units.",
  "overall": "Stabilize on Marine production, add Tank tech, and expand once the front is secure.",
  "priority": "The current bottleneck is converting early economy into safe production and tech.",
  "economy": "Keep worker and supply flow healthy, and prepare a natural expansion when the main is saturated and pressure is controlled.",
  "construction": "Use Barracks production first, then add Factory Tech Lab for Siege Tanks before unrelated tech.",
  "combat": "Hold defensively until Marines are grouped with Tank support, then look for a cautious timing attack.",
  "avoid": "Do not send scattered Marines across the map before the army is grouped."
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

    def _stringify_prediction(self, value) -> str:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value or "")

    def _safe_parse(self, response: str) -> tuple[str, dict]:
        allowed_fields = ["overall", "priority", "economy", "construction", "combat", "avoid"]
        predicted_observation = ""
        try:
            payload = json.loads(extract_code(response))
            if isinstance(payload, list):
                directive = {"overall": " ".join(str(item).strip() for item in payload if str(item).strip())}
            elif isinstance(payload, dict):
                predicted_observation = self._stringify_prediction(payload.get("predicted_observation_30_ticks", ""))
                directive = {
                    field: payload[field].strip()
                    for field in allowed_fields
                    if isinstance(payload.get(field), str) and payload[field].strip()
                }
                if "economy" not in directive and isinstance(payload.get("resource"), str) and payload["resource"].strip():
                    directive["economy"] = payload["resource"].strip()
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
        return predicted_observation, directive

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

        predicted_observation, directive = self._safe_parse(response)
        return predicted_observation, directive, self.think, self.chat_history
