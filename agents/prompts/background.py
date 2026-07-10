from utils.format import construct_ordered_list


strategy_prompt = """
Our final aim: destroy all enemies as soon as possible.
Our strategy:
- Resource collection: produce workers and gather minerals and gas
- Development: build attacking units and structures
- Attacking: concentrate forces to search and destroy enemies proactively
""".strip()


def construct_plan_example(race: str):
    if race == "Terran":
        return """
Following are some examples:
- Do nothing and just wait;
- Train 1/2/3/... SCV/Marine/Viking/...
- Build a supply depot;
- Upgrade to Orbital Command;
- Attack visible enemies;
- ...
""".strip()
    elif race == "Protoss":
        return """
Following are some examples:
- Do nothing and just wait;
- Train 1/2/3/... Probe/Stalker/Zealot/...
- Build a Pylon;
- Upgrade to Warp Gate;
- Attack visible enemies;
- ...
""".strip()
    elif race == "Zerg":
        return """
Following are some examples:
- Do nothing and just wait;
- Train 1/2/3/... Drone/Zergling/Hydralisk/...
- Build a Hatchery;
- Upgrade to Lair;
- Attack visible enemies;
- ...
""".strip()
    else:
        raise ValueError(f"Unknown race: {race}")


def construct_rules(race: str):
    rules = [
        "Commands should be natural language, instead of code.",
        "Produce as many units with the strongest attack power as possible.",
        "The total cost of all commands should not exceed the current resources (minerals and gas).",
        "Commands should not build redundant structures(e.g. 2 Refinery while one is not fully utilized).",
        "Commands should not use abilities that are not supported currently.",
        "Commands should not build a structure that is not needed now (e.g. build a Missile Turret but there is no enemy air unit).",
        "The unit production list capacity of structures is 5. If the list is full, do not add more units to it.",
    ]
    if race == "Terran":
        rules += [
            "Commands should not send SCV or MULE to gather resources because the system will do it automatically.",
            "Commands should not train too many SCVs or MULEs, whose number should not exceed the capacity of CommandCenter and Refinery.",
            "Commands can construct a new one Supply Depot only when the remaining unused supply is less than 7.",
        ]
    elif race == "Protoss":
        rules += [
            "Commands should not send Probe to gather resources because the system will do it automatically.",
            "Commands should not train too many Probes, whose number should not exceed the capacity of Nexus and Assimilator.",
            "Commands can construct a new one Pylon only when the remaining unused supply is less than 7.",
        ]
    elif race == "Zerg":
        rules += [
            "Commands should not send Drone to gather resources because the system will do it automatically.",
            "Commands should not train too many Drones, whose number should not exceed the capacity of Hatchery and Extractor.",
            "Commands can construct a new one Overlord only when the remaining unused supply is less than 7.",
            "Commands should not train another Overlord if any [Egg] unit in 'Own units' has 'Production list: Overlord'.",
        ]
    else:
        raise ValueError(f"Unknown race: {race}")
    return rules


role_prompt = """
As a top-tier StarCraft II background strategist, your task is to give one or more medium-term strategic commands based on the current game state and the reason you were consulted. Do NOT output executable actions — the executor will translate your commands into actions.
""".strip()


def create_plan_prompt(race: str, rules: list[str], obs_text: str, background_request: str = ""):
    plan_example_prompt = construct_plan_example(race)
    rules_prompt = "Rule checklist:\n" + construct_ordered_list(rules)
    request_text = background_request.strip() or "Regular strategic check — provide updated commands for the next phase."

    return f"""
{role_prompt}

### Why You Were Consulted
{request_text}

### Aim
{strategy_prompt}

### Current Game State
{obs_text}

### Rules
{rules_prompt}

### Examples
{plan_example_prompt}

Think step by step, and then give commands as a list JSON in the following format wrapped with triple backticks:
```
[
    "<command_1>",
    "<command_2>",
    ...
]
```
    """.strip()


def create_plan_critic_prompt(rules: list[str], obs_text: str, plans: list[str]):
    rules_text = construct_ordered_list(rules)
    plans_text = construct_ordered_list(plans)
    return """
As a top-tier StarCraft II player, your task is to check if the given commands for current game state violate any rules.

### Current Game State
%s

### Given Commands
%s

### Rules Checklist
%s

Analyze the given rules one by one, and then provide a summary for errors at the end as follows, wrapped with triple backticks::
```
{
    "errors": [
        "Error 1: ...",
        "Error 2: ...",
        ...
    ],
    "error_number": 0/1/2/...
}
```
    """.strip() % (obs_text, plans_text, rules_text)

