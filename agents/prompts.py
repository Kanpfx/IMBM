strategy_prompt = """
Our final aim: defeat the enemy as efficiently as possible.

Our action preferences:
- Resources: keep resource collection and spending healthy.
- Development: build structures and develop technology at appropriate timings.
- Combat: defend against enemy attacks when needed, and organize reasonable attacks with our army.
""".strip()


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
