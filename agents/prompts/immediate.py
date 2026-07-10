role_prompt = """
As a top-tier StarCraft II executor, your task is to give some actions to finish the given task as possible as you can. You must also request strategic guidance from the background model when facing strategic uncertainty.
""".strip()


observation_role_prompt = """
As a top-tier StarCraft II executor, your task is to give some actions to finish the given task as possible as you can. You must also predict the near-future game state and request strategic guidance from the background model when facing strategic uncertainty.
""".strip()


executor_rules = [
    "Do not give any action that is irrelevant to the task.",
    "Each of units can only be used in the whole response once at most.",
    "If a unit is already performing an action as given task, you should ignore it, instead of giving a repeated action for it.",
    "If one task cannot be finished, just ignore it.",
    "If resource is not enough, just complete the most important part of the task.",
]


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

def get_role_prompt(include_observation: bool) -> str:
    # -observation 开启时，IM prompt 才要求预测观测。
    return observation_role_prompt if include_observation else role_prompt


def get_rules_prompt(include_observation: bool) -> str:
    # 预测观测规则按需加入，默认减少输出负担。
    rules = executor_rules + ([prediction_rule] if include_observation else []) + [background_request_rule]
    return "Rule checklist:\n" + "\n".join([f"{i+1}. {rule}" for i, rule in enumerate(rules)])


default_action_format_prompt = """
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
    "background_reason": "<reason why we request updated strategic tasks>"
}
```
""".strip()


observation_action_format_prompt = """
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


def get_action_format_prompt(include_observation: bool) -> str:
    return observation_action_format_prompt if include_observation else default_action_format_prompt


default_action_example_prompt = """
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
  "background_reason": "We are under heavy attack and need updated strategic tasks."
}
```
""".strip()


observation_action_example_prompt = """
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


def get_action_example_prompt(include_observation: bool) -> str:
    return observation_action_example_prompt if include_observation else default_action_example_prompt


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


def create_im_prompt(obs_text: str, plan_text: str | None, include_observation: bool = False):
    plan_section = plan_text or "[No active tasks — act based on the current game state]"
    return f"""
{get_role_prompt(include_observation)}

### Current Game State
{obs_text}

### Given Tasks
{plan_section}

### Rules
{get_rules_prompt(include_observation)}

### Required JSON Output
{get_action_format_prompt(include_observation)}

### Example JSON Output
{get_action_example_prompt(include_observation)}

Please output only the well-formed JSON object that you have decided on, wrapped with triple backticks, with no extra text.
    """.strip()
