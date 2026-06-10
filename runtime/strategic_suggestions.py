from __future__ import annotations

from runtime.action_queue import QUEUE_NAMES, WAITING
from sc2.ids.unit_typeid import UnitTypeId


def build_strategic_suggestions(player, max_suggestions: int = 16) -> list[str]:
    """Build lightweight, code-triggered hints for BM."""
    if max_suggestions <= 0:
        return []

    suggestions: list[str] = []
    suggestions.extend(_generic_suggestions(player))

    if _own_race(player) == "Terran":
        suggestions.extend(_terran_suggestions(player))

    suggestions.extend(_queue_suggestions(player))
    return _dedupe(suggestions)[:max_suggestions]


def _generic_suggestions(player) -> list[str]:
    suggestions = []
    game_time = _number(player, "time")
    minerals = _number(player, "minerals")
    supply_left = _number(player, "supply_left")
    supply_cap = _number(player, "supply_cap")
    supply_workers = _number(player, "supply_workers")
    supply_army = _number(player, "supply_army")
    townhalls = _amount(getattr(player, "townhalls", []))
    enemy_units = getattr(player, "enemy_units", [])
    visible_enemy_units = _amount(enemy_units)

    if minerals >= 1000:
        suggestions.append(
            f"Because minerals are very high at {minerals} (>=1000), it is better to spend now on expansion, production, tech, or supply instead of adding scouting tasks."
        )
    elif minerals >= 500:
        suggestions.append(
            f"Because minerals are high at {minerals} (>=500), it is better to add concrete spending tasks for workers, supply, production, tech, or expansion."
        )

    target_workers = townhalls * 16
    if townhalls and supply_workers < target_workers:
        suggestions.append(
            f"Because workers are {supply_workers}/{target_workers} across {townhalls} town hall(s), one worker-production task is useful if a base can train workers."
        )

    if supply_left <= 7 and supply_cap < 200:
        suggestions.append(
            f"Because unused supply is only {supply_left} (<=7) out of {supply_cap}, it is better to secure supply before adding many production tasks."
        )

    if 60 < game_time < 150:
        suggestions.append(
            f"Because game time is {game_time}s and early pressure often arrives around 03:00, it is better to prepare basic production or defense by about 02:30."
        )
    elif 150 <= game_time < 300:
        suggestions.append(
            f"Because game time is {game_time}s and the 03:00 pressure window is close, it is better to prioritize basic defense or army production over extra scouting."
        )

    if game_time > 300 and supply_army > 15 and visible_enemy_units < 8:
        suggestions.append(
            f"Because game time is {game_time}s, army supply is {supply_army} (>15), and only {visible_enemy_units} enemy unit(s) are visible, it is reasonable to look for the enemy or plan a careful attack."
        )

    if supply_army == 0 and not _exists(enemy_units):
        suggestions.append(
            f"Because army supply is {supply_army} and visible enemy units are {visible_enemy_units}, prefer economy or production setup over generic combat scout or monitor tasks."
        )

    if _exists(enemy_units):
        suggestions.append(
            f"Because {visible_enemy_units} enemy unit(s) are visible, combat tasks should focus on immediate defense or protecting workers and bases."
        )

    return suggestions


def _terran_suggestions(player) -> list[str]:
    suggestions = []
    minerals = _number(player, "minerals")
    vespene = _number(player, "vespene")
    supply_left = _number(player, "supply_left")
    supply_cap = _number(player, "supply_cap")
    supply_workers = _number(player, "supply_workers")
    townhalls = _amount(getattr(player, "townhalls", []))

    depots = _total_amount(player, UnitTypeId.SUPPLYDEPOT, UnitTypeId.SUPPLYDEPOTLOWERED)
    ready_depots = _ready_structures(player, UnitTypeId.SUPPLYDEPOT, UnitTypeId.SUPPLYDEPOTLOWERED)
    pending_depots = _pending(player, UnitTypeId.SUPPLYDEPOT)
    refineries = _total_amount(player, UnitTypeId.REFINERY)
    pending_refineries = _pending(player, UnitTypeId.REFINERY)
    barracks = _total_amount(player, UnitTypeId.BARRACKS, UnitTypeId.BARRACKSFLYING)
    ready_barracks = _ready_structures(player, UnitTypeId.BARRACKS)
    idle_barracks = _idle_ready_structures(player, UnitTypeId.BARRACKS)
    barracks_techlabs = _total_amount(player, UnitTypeId.BARRACKSTECHLAB)
    barracks_addons = barracks_techlabs + _total_amount(player, UnitTypeId.BARRACKSREACTOR)
    factories = _total_amount(player, UnitTypeId.FACTORY, UnitTypeId.FACTORYFLYING)
    ready_factories = _ready_structures(player, UnitTypeId.FACTORY)
    factory_techlabs = _total_amount(player, UnitTypeId.FACTORYTECHLAB)
    factory_addons = factory_techlabs + _total_amount(player, UnitTypeId.FACTORYREACTOR)
    starports = _total_amount(player, UnitTypeId.STARPORT, UnitTypeId.STARPORTFLYING)
    ready_command_centers = _ready_structures(player, UnitTypeId.COMMANDCENTER)
    idle_townhalls = _idle_ready_structures(
        player,
        UnitTypeId.COMMANDCENTER,
        UnitTypeId.ORBITALCOMMAND,
        UnitTypeId.PLANETARYFORTRESS,
    )
    orbitals = _total_amount(player, UnitTypeId.ORBITALCOMMAND)
    marines = _total_amount(player, UnitTypeId.MARINE)
    marauders = _total_amount(player, UnitTypeId.MARAUDER)
    siege_tanks = _total_amount(player, UnitTypeId.SIEGETANK)

    if depots < 1:
        if _can_build(player, UnitTypeId.SUPPLYDEPOT) or minerals >= 100:
            suggestions.append(
                f"Because depots={depots} and minerals={minerals} can cover a 100-mineral Supply Depot, it is better to add one economy_build task for the first Supply Depot with an SCV."
            )
        else:
            suggestions.append(
                f"Because depots={depots} and ready_depots={ready_depots}, keep early tasks focused on the first Supply Depot before Barracks or infantry production."
            )
    elif supply_left <= 7 and supply_cap < 200 and pending_depots < 1:
        suggestions.append(
            f"Because unused supply is {supply_left} (<=7) and pending_depots={pending_depots}, it is better to add one concrete economy_build task for another Supply Depot."
        )

    if refineries < 1 and pending_refineries < 1 and (minerals >= 75 or _can_build(player, UnitTypeId.REFINERY)):
        suggestions.append(
            f"Because refineries={refineries}, pending_refineries={pending_refineries}, and minerals={minerals} can cover a 75-mineral Refinery, it is better to build one Refinery on a nearby vespene geyser with an SCV."
        )
    elif vespene == 0 and refineries < 1:
        suggestions.append(
            f"Because vespene={vespene} and refineries={refineries}, avoid tech tasks that need gas until a Refinery task is planned or pending."
        )

    if ready_depots < 1:
        suggestions.append(
            f"Because ready_depots={ready_depots}, avoid Barracks, Marine, Marauder, or add-on production tasks until a Supply Depot is ready."
        )
    elif barracks < 1:
        if _can_build(player, UnitTypeId.BARRACKS) or minerals >= 150:
            suggestions.append(
                f"Because ready_depots={ready_depots}, barracks={barracks}, and minerals={minerals} can cover a 150-mineral Barracks, it is better to add one economy_build task for a Barracks with an SCV."
            )
        else:
            suggestions.append(
                f"Because ready_depots={ready_depots} but barracks={barracks}, Barracks is the next core structure; avoid infantry-production wording until it exists."
            )

    if ready_barracks < 1:
        suggestions.append(
            f"Because ready_barracks={ready_barracks}, avoid Marine, Marauder, add-on, or \"available Barracks\" production tasks for now."
        )
    else:
        if marines < 2 and idle_barracks > 0:
            suggestions.append(
                f"Because ready_barracks={ready_barracks}, idle_barracks={idle_barracks}, and marines={marines}, it is reasonable to add a production_tech task for a small number of Marines."
            )
        if barracks_addons < ready_barracks and minerals >= 50 and vespene >= 25:
            suggestions.append(
                f"Because ready_barracks={ready_barracks}, barracks_addons={barracks_addons}, minerals={minerals}, and vespene={vespene}, a Tech Lab or Reactor can be considered after basic infantry production is possible."
            )
        if marauders < 1 and barracks_techlabs > 0 and vespene >= 25:
            suggestions.append(
                f"Because barracks_techlabs={barracks_techlabs}, marauders={marauders}, and vespene={vespene}, Marauder production can be added as a specific production_tech task."
            )

    if ready_barracks > 0 and refineries >= 1 and factories < 1 and (vespene >= 100 or _can_build(player, UnitTypeId.FACTORY)):
        suggestions.append(
            f"Because ready_barracks={ready_barracks}, refineries={refineries}, factories={factories}, and vespene={vespene}, a concrete Factory task is a useful next Terran tech step."
        )

    if ready_factories > 0:
        if factory_addons < ready_factories and minerals >= 50 and vespene >= 25:
            suggestions.append(
                f"Because ready_factories={ready_factories}, factory_addons={factory_addons}, minerals={minerals}, and vespene={vespene}, a Factory Tech Lab or Reactor can come before advanced Factory-unit production."
            )
        if siege_tanks < 2 and factory_techlabs > 0 and vespene >= 125:
            suggestions.append(
                f"Because factory_techlabs={factory_techlabs}, siege_tanks={siege_tanks}, and vespene={vespene}, Siege Tank production is a stronger defensive production_tech task than generic combat."
            )
        if starports < 1 and _can_build(player, UnitTypeId.STARPORT):
            suggestions.append(
                f"Because ready_factories={ready_factories} and starports={starports}, a Starport task can extend the Terran tech path."
            )

    if ready_command_centers > 0 and orbitals < 1 and supply_workers >= 16 and minerals >= 150:
        suggestions.append(
            f"Because ready_command_centers={ready_command_centers}, orbitals={orbitals}, workers={supply_workers}, and minerals={minerals}, upgrading toward Orbital Command is better than adding more SCV-only tasks."
        )

    if idle_townhalls > 0 and townhalls and supply_workers < townhalls * 16:
        suggestions.append(
            f"Because idle_townhalls={idle_townhalls} and workers are {supply_workers}/{townhalls * 16}, one SCV-training task is useful, but avoid filling queues only with SCVs."
        )

    if minerals >= 550 and townhalls < 2 and ready_depots > 0 and ready_barracks > 0:
        suggestions.append(
            f"Because minerals={minerals} (>=550), townhalls={townhalls}, ready_depots={ready_depots}, and ready_barracks={ready_barracks}, an expansion Command Center can be considered after supply, Refinery, and Barracks basics are covered."
        )

    return suggestions


def _queue_suggestions(player) -> list[str]:
    store = getattr(player, "action_queue_store", None)
    queues = getattr(store, "queues", None)
    if not isinstance(queues, dict):
        return []

    suggestions = []
    for queue_name in QUEUE_NAMES:
        waiting_count = sum(
            1
            for task in queues.get(queue_name, [])
            if task.get("status") == WAITING and task.get("task")
        )
        if waiting_count:
            suggestions.append(
                f"Because {queue_name} already has {waiting_count} waiting task(s), only append if the new task is more specific, non-duplicate, and immediately useful."
            )
    return suggestions


def _own_race(player) -> str:
    config = getattr(player, "config", None)
    return str(getattr(config, "own_race", ""))


def _number(obj, name: str, default: int = 0) -> int:
    try:
        return int(getattr(obj, name, default))
    except (TypeError, ValueError):
        return default


def _amount(collection) -> int:
    if collection is None:
        return 0
    amount = getattr(collection, "amount", None)
    if amount is not None:
        return int(amount)
    try:
        return len(collection)
    except TypeError:
        return 0


def _exists(collection) -> bool:
    exists = getattr(collection, "exists", None)
    if exists is not None:
        return bool(exists)
    return _amount(collection) > 0


def _units(player, unit_type: UnitTypeId):
    try:
        return player.units(unit_type)
    except Exception:
        return []


def _structures(player, unit_type: UnitTypeId):
    try:
        return player.structures(unit_type)
    except Exception:
        return []


def _ready_structures(player, *unit_types: UnitTypeId) -> int:
    total = 0
    for unit_type in unit_types:
        structures = _structures(player, unit_type)
        total += _amount(getattr(structures, "ready", []))
    return total


def _idle_ready_structures(player, *unit_types: UnitTypeId) -> int:
    total = 0
    for unit_type in unit_types:
        structures = getattr(_structures(player, unit_type), "ready", [])
        total += _amount(getattr(structures, "idle", []))
    return total


def _pending(player, unit_type: UnitTypeId) -> int:
    try:
        return int(player.already_pending(unit_type))
    except Exception:
        return 0


def _can_build(player, unit_type: UnitTypeId) -> bool:
    try:
        return bool(player._can_build(unit_type))
    except Exception:
        try:
            return bool(player.can_afford(unit_type)) and _pending(player, unit_type) < 1
        except Exception:
            return False


def _total_amount(player, *unit_types: UnitTypeId) -> int:
    total = 0
    for unit_type in unit_types:
        try:
            total += int(player.get_total_amount(unit_type))
        except Exception:
            total += _amount(_units(player, unit_type))
            total += _amount(_structures(player, unit_type))
            total += _pending(player, unit_type)
    return total


def _dedupe(items: list[str]) -> list[str]:
    result = []
    seen = set()
    for item in items:
        item = item.strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
