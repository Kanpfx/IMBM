"""Ares bot entry point for the LLM-controlled game runtime."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from ares import AresBot
from ares.behaviors.combat.individual import KeepUnitSafe
from ares.consts import ALL_STRUCTURES, TOWNHALL_TYPES, UnitRole
from cython_extensions import cy_closest_to, cy_distance_to_squared, cy_towards
from loguru import logger
from sc2.data import Race, Result
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from game.bot.consts import UNIT_TYPE_TO_NUM_REPAIRERS
from game.control.controller import LLMGameController


class WhyBot(AresBot):
    def __init__(
        self,
        game_step_override: int | None = None,
        *,
        tactic_name: str = "BattleCruiserRush",
        run_metadata: dict[str, str | bool] | None = None,
        log_directory: Path | None = None,
    ) -> None:
        super().__init__(game_step_override)
        self.opening_chat_tag: bool = False
        self.injured_general_unit_to_repairing_scvs: dict[int, set[int]] = {}
        self._terran_bunker_finder_activated: bool = False
        self._last_iteration: int = -1
        self.tactic_name = tactic_name
        self.run_metadata = run_metadata or {}
        self.log_directory = log_directory
        self.llm_controller: LLMGameController | None = None

    async def on_start(self) -> None:
        await super().on_start()
        self.llm_controller = LLMGameController(
            tactic_name=self.tactic_name,
            run_metadata=self.run_metadata,
            log_directory=self.log_directory,
        )
        if not self.llm_controller.active:
            raise RuntimeError("LLM_MODEL, LLM_BASE_URL and LLM_API_KEY are required")
        # Preserve Ares manager updates while permanently disabling its YAML
        # BuildOrderRunner. The model is now the only non-automatic decision source.
        self.build_order_runner.set_build_completed()
        logger.info(
            "Single-model mode started (tactic: {}, logs: {})",
            self.tactic_name,
            self.llm_controller.telemetry.directory,
        )

    async def on_step(self, iteration: int) -> None:
        await super().on_step(iteration)
        self._last_iteration = iteration
        if self.supply_used < 1:
            await self.client.leave()

        if self.llm_controller is None:
            raise RuntimeError("model controller was not initialized")
        await self.llm_controller.run_iteration(self, iteration)
        if not self.opening_chat_tag and self.time > 5.0:
            await self.chat_send("Tag: LLM", team_only=True)
            await self.chat_send(f"Tag: {self.race.name}", team_only=True)
            self.opening_chat_tag = True

    async def on_end(self, game_result: Result) -> None:
        if self.llm_controller is not None:
            try:
                self.llm_controller.telemetry.update_metadata(
                    **self._result_metadata(game_result),
                    completed_at=datetime.now()
                    .astimezone()
                    .isoformat(timespec="seconds"),
                )
            except Exception as exc:
                logger.warning("Failed to write match result metadata: {}", exc)
        await super().on_end(game_result)

    def _result_metadata(self, game_result: Result) -> dict[str, Any]:
        score = getattr(getattr(self, "state", None), "score", None)
        result_name = getattr(game_result, "name", str(game_result))
        return {
            "result": result_name,
            "final_iteration": self._last_iteration,
            "game_time_seconds": round(float(getattr(self, "time", 0.0)), 1),
            "final_resources": {
                "minerals": int(getattr(self, "minerals", 0)),
                "vespene": int(getattr(self, "vespene", 0)),
                "supply_used": int(getattr(self, "supply_used", 0)),
                "supply_cap": int(getattr(self, "supply_cap", 0)),
                "workers": int(getattr(self, "supply_workers", 0)),
                "army_supply": int(getattr(self, "supply_army", 0)),
            },
            "score": {
                "collected_minerals": getattr(score, "collected_minerals", 0),
                "collected_vespene": getattr(score, "collected_vespene", 0),
                "killed_value_units": getattr(score, "killed_value_units", 0),
                "killed_value_structures": getattr(score, "killed_value_structures", 0),
                "idle_worker_time": getattr(score, "idle_worker_time", 0),
            },
        }

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float) -> None:
        await super().on_unit_took_damage(unit, amount_damage_taken)

        compare_health: float = max(50.0, unit.health_max * 0.09)
        if unit.health < compare_health:
            self.mediator.cancel_structure(structure=unit)

    def _general_repair(self) -> None:
        self._execute_scv_to_general_repair()

        for unit in self.all_own_units:
            type_id: UnitTypeId = unit.type_id
            if (
                unit.health_percentage >= 1.0
                or not unit.is_ready
                or (cy_distance_to_squared(unit.position, self.start_location) > 2000.0)
                or type_id not in UNIT_TYPE_TO_NUM_REPAIRERS
            ):
                continue
            if type_id in ALL_STRUCTURES and unit.health_percentage > 0.95:
                continue

            if type_id == UnitTypeId.BUNKER and not unit.has_cargo:
                continue

            if type_id in UNIT_TYPE_TO_NUM_REPAIRERS:
                if (
                    unit.is_structure
                    and type_id not in TOWNHALL_TYPES
                    and cy_distance_to_squared(unit.position, self.start_location)
                    > 6500
                ):
                    continue
                if type_id == UnitTypeId.HELLION and self.enemy_race == Race.Terran:
                    continue
                num_scvs_required: int = UNIT_TYPE_TO_NUM_REPAIRERS[unit.type_id]
                if unit.tag in self.injured_general_unit_to_repairing_scvs:
                    num_scvs_required -= len(
                        self.injured_general_unit_to_repairing_scvs[unit.tag]
                    )
                for _ in range(num_scvs_required):
                    if worker := self.mediator.select_worker(
                        target_position=unit.position,
                        force_close=True,
                        min_health_perc=0.45,
                    ):
                        if unit.tag in self.injured_general_unit_to_repairing_scvs:
                            self.injured_general_unit_to_repairing_scvs[unit.tag].add(
                                worker.tag
                            )
                        else:
                            self.injured_general_unit_to_repairing_scvs[unit.tag] = {
                                worker.tag
                            }
                        self.mediator.assign_role(
                            tag=worker.tag, role=UnitRole.REPAIRING
                        )

    def _execute_scv_to_general_repair(self) -> None:
        """Maintain SCV repair assignments and release completed workers."""
        remove_tags: list[int] = []
        remove_medics: dict[int, int] = {}
        for (
            injured_tag,
            medic_tags,
        ) in self.injured_general_unit_to_repairing_scvs.items():
            injured: Unit | None = self.unit_tag_dict.get(injured_tag)
            if not injured or injured.health_percentage >= 1.0:
                remove_tags.append(injured_tag)
                continue

            medics: list[Unit] = []
            for tag in medic_tags:
                medic: Unit | None = self.unit_tag_dict.get(tag)
                if not medic or (
                    medic.health_percentage < 0.4 and injured_tag not in remove_tags
                ):
                    remove_medics[injured_tag] = tag
                else:
                    medics.append(medic)

            self._scvs_to_general_repair_logic(injured, medics)

        for tag in remove_tags:
            medic_tags: set[int] = self.injured_general_unit_to_repairing_scvs[tag]
            self.mediator.batch_assign_role(tags=medic_tags, role=UnitRole.GATHERING)
            self.mediator.assign_role(tag=tag, role=UnitRole.ATTACKING)
            self.injured_general_unit_to_repairing_scvs.pop(tag)

        for tag, remove_tag in remove_medics.items():
            self.injured_general_unit_to_repairing_scvs[tag].remove(remove_tag)

    def _scvs_to_general_repair_logic(self, injured: Unit, medics: list[Unit]) -> None:
        grid: np.ndarray = self.mediator.get_ground_avoidance_grid

        for medic in medics:
            # avoid biles etc
            if not self.mediator.is_position_safe(grid=grid, position=medic.position):
                self.register_behavior(KeepUnitSafe(medic, grid))
                continue

            if medic.is_repairing:
                continue

            medic(AbilityId.EFFECT_REPAIR_SCV, injured)

    def _mules(self) -> None:
        orbital_type = UnitTypeId.ORBITALCOMMAND
        structures_dict: dict[
            UnitTypeId, list[Unit]
        ] = self.mediator.get_own_structures_dict
        for orbital in [
            structure
            for structure in structures_dict[orbital_type]
            if structure.energy >= 50
        ]:
            nearby_minerals: list[Unit] = [
                mineral
                for mineral in self.mineral_field
                if cy_distance_to_squared(mineral.position, orbital.position) < 100.0
            ]
            if nearby_minerals:
                target = max(nearby_minerals, key=lambda unit: unit.mineral_contents)
                orbital(AbilityId.CALLDOWNMULE_CALLDOWNMULE, target)

    def _look_for_terran_bunker(self) -> None:
        """Scout around the natural for an early Terran proxy bunker."""
        if (
            self.enemy_race == Race.Terran
            and not self._terran_bunker_finder_activated
            and self.time > 77.0
        ):
            natural_location: Point2 = self.mediator.get_own_nat
            if worker := self.mediator.select_worker(target_position=natural_location):
                self.mediator.assign_role(tag=worker.tag, role=UnitRole.MAP_CONTROL)

                radius = 9
                num_points = 10

                scouting_positions = [
                    Point2(
                        (
                            natural_location.x
                            + radius * math.cos(2 * math.pi * i / num_points),
                            natural_location.y
                            + radius * math.sin(2 * math.pi * i / num_points),
                        )
                    )
                    for i in range(num_points)
                ]
                scouting_positions = [
                    s for s in scouting_positions if self.in_pathing_grid(s)
                ]

                for i, position in enumerate(scouting_positions):
                    worker.move(position, queue=i != 0)

                logger.info(
                    "{} - Sent scout to circle around natural", self.time_formatted
                )

                self._terran_bunker_finder_activated = True
                return

        if self._terran_bunker_finder_activated and (
            scouts := self.mediator.get_units_from_role(
                role=UnitRole.MAP_CONTROL, unit_type=UnitTypeId.SCV
            )
        ):
            for scout in scouts:
                if proxies := self.get_enemy_proxies(30.0, scout.position):
                    scout.attack(cy_closest_to(scout.position, proxies).position)

                elif self.mediator.get_enemy_expanded:
                    self.mediator.assign_role(tag=scout.tag, role=UnitRole.GATHERING)

                elif scout.is_idle:
                    if self.time < 125.0:
                        scout.move(
                            Point2(
                                cy_towards(
                                    self.mediator.get_own_nat,
                                    self.game_info.map_center,
                                    10.0,
                                )
                            )
                        )
                    else:
                        self.mediator.assign_role(
                            tag=scout.tag, role=UnitRole.GATHERING
                        )
