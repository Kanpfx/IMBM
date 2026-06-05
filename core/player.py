import asyncio
import time

from agents import BmAgent, ImAgent
from core.base_player import BasePlayer
from core.economy import EconomyMixin
from sc2.ids.unit_typeid import UnitTypeId
from runtime.directive import Directive, DirectiveStore


class ImBmPlayer(EconomyMixin, BasePlayer):
    def __init__(
        self,
        config,
        *args,
        enable_bm=False,
        bm_model_name=None,
        bm_generation_config=None,
        bm_llm_client=None,
        **kwargs,
    ):
        BasePlayer.__init__(self, config, *args, **kwargs)

        im_agent_config = {
            "model_name": self.model_name,
            "generation_config": self.generation_config,
            "llm_client": self.llm_client,
        }
        self.im_agent = ImAgent(config.own_race, **im_agent_config)

        self.enable_bm = enable_bm
        self.bm_agent = None
        if enable_bm:
            bm_agent_config = {
                "model_name": bm_model_name,
                "generation_config": bm_generation_config,
                "llm_client": bm_llm_client,
            }
            self.bm_agent = BmAgent(config.own_race, **bm_agent_config)

        self.directive_store = DirectiveStore()
        self.bm_task = None
        self.bm_task_reason = ""
        self.directive_ttl = 360
        self.decision_interval = 30
        self.decision_minerals = 50

        self.scv_auto_attack_distance = 4
        self.scv_auto_attack_time = 240

    async def _auto_micro(self):
        await self.distribute_workers()
        for unit in self.units:
            if unit.type_id in [UnitTypeId.MULE] or unit.is_constructing_scv:
                continue
            enemies_in_range = self.enemy_units.in_attack_range_of(unit)
            if enemies_in_range.exists:
                target = self.get_lowest_health_enemy(enemies_in_range)
                if target:
                    unit.attack(target)
            else:
                nearby_enemies = self.enemy_units.closer_than(
                    self.scv_auto_attack_distance,
                    unit.position,
                )
                nearby_enemies = nearby_enemies.closer_than(
                    self.scv_auto_attack_distance,
                    self.start_location,
                )
                target_enemy = self.get_lowest_health_enemy(nearby_enemies)
                if unit.type_id in [UnitTypeId.SCV] and self.time < self.scv_auto_attack_time and target_enemy:
                    unit.attack(target_enemy)

    def _snapshot_metrics(self, iteration: int) -> dict:
        return {
            "iteration": iteration,
            "time_seconds": int(self.time),
            "minerals": self.minerals,
            "vespene": self.vespene,
            "supply_army": self.supply_army,
            "supply_workers": self.supply_workers,
            "supply_left": self.supply_left,
            "n_structures": len(self.structures),
            "n_visible_enemy_units": len(self.enemy_units),
            "n_visible_enemy_structures": len(self.enemy_structures),
        }

    def _active_bm_task(self) -> bool:
        return self.bm_task is not None and not self.bm_task.done()

    def _current_iteration(self, fallback: int) -> int:
        try:
            return self.state.game_loop // 4
        except Exception:
            return fallback

    def _directive_to_im_text(self, directive: Directive | None) -> str | None:
        if directive is None:
            return None

        fields = [
            ("overall", "Overall Guidance"),
            ("priority", "Priority Guidance"),
            ("economy", "Economy Guidance"),
            ("resource", "Resource Guidance"),
            ("construction", "Construction Guidance"),
            ("combat", "Combat Guidance"),
            ("avoid", "Avoid Guidance"),
        ]
        lines = []
        for key, label in fields:
            value = directive.data.get(key)
            if isinstance(value, str) and value.strip():
                lines.append(f"- {label}: {value.strip()}")

        if not lines:
            return None
        return "Current Strategic Guidance:\n" + "\n".join(lines)

    async def _run_bm_background(
        self,
        obs_text: str,
        metrics: dict,
        actions: list,
        iteration: int,
        trigger_reason: str,
    ):
        start_time = time.time()
        try:
            loop = asyncio.get_running_loop()
            bm_predicted_observation_30_ticks, directive_data, bm_think, bm_chat_history = await loop.run_in_executor(
                None,
                lambda: self.bm_agent.run(
                    obs_text=obs_text,
                    metrics=metrics,
                    actions=actions,
                    background_request=trigger_reason,
                ),
            )
            issued_at_tick = iteration
            valid_until_tick = issued_at_tick + self.directive_ttl
            directive = Directive(
                data=directive_data,
                issued_at_tick=issued_at_tick,
                valid_until_tick=valid_until_tick,
                source="BM",
            )
            self.directive_store.write(directive)
            self.logging("bm_latency", round(time.time() - start_time, 4), save_trace=True)
            self.logging("bm_trigger_reason", trigger_reason, save_trace=True)
            self.logging("bm_predicted_observation_30_ticks", bm_predicted_observation_30_ticks, save_trace=True, print_log=False)
            self.logging("bm_think", bm_think, save_trace=True, print_log=False)
            self.logging("bm_chat_history", bm_chat_history, save_trace=True, print_log=False)
            self.logging("directive", directive.to_dict(), save_trace=True)
        except asyncio.CancelledError:
            self.logging("bm_cancelled", trigger_reason, save_trace=True)
            raise
        except Exception as exc:
            self.logging("bm_error", str(exc), level="error", save_trace=True)

    async def _maybe_start_bm(
        self,
        iteration: int,
        obs_text: str,
        actions: list,
        request_background: bool,
        background_reason: str,
        directive_before_im: Directive | None,
        latest_directive: Directive | None,
    ):
        if not self.enable_bm or self.bm_agent is None:
            return

        reasons = []
        if request_background:
            reasons.append("im_request")
        elif latest_directive is None:
            reasons.append("cold_start")
        elif directive_before_im is None or not latest_directive.is_valid(iteration):
            reasons.append("guidance_expired")

        trigger_reason = ",".join(reasons)
        if not trigger_reason:
            return

        if self._active_bm_task():
            if request_background and not self.bm_task_reason.startswith("im_request"):
                self.bm_task.cancel()
                self.logging("bm_cancelled_for_im_request", self.bm_task_reason, save_trace=True)
            else:
                self.logging("bm_triggered", False, save_trace=True)
                self.logging("bm_skip_reason", "bm_already_running", save_trace=True)
                return

        if background_reason:
            trigger_reason += f": {background_reason}"

        metrics = self._snapshot_metrics(iteration)

        self.logging("bm_triggered", True, save_trace=True)
        self.logging("bm_trigger_reason", trigger_reason, save_trace=True)
        self.bm_task_reason = trigger_reason
        self.bm_task = asyncio.create_task(
            self._run_bm_background(
                obs_text=obs_text,
                metrics=metrics,
                actions=actions,
                iteration=iteration,
                trigger_reason=trigger_reason,
            )
        )

    async def run(self, iteration: int):
        await self._auto_micro()

        if iteration % self.decision_interval != 0:
            if iteration % 10 == 0:
                self.log_current_iteration(iteration)
            return

        if self.minerals < self.decision_minerals:
            if iteration % 10 == 0:
                self.log_current_iteration(iteration)
            self.logging("decision_skipped", True, save_trace=True)
            self.logging("decision_skip_reason", f"minerals_below_{self.decision_minerals}", save_trace=True)
            return

        self.log_current_iteration(iteration)
        obs_text = await self.obs_to_text()

        latest_directive = self.directive_store.latest()
        active_directive = self.directive_store.read(iteration)
        directive_text = self._directive_to_im_text(active_directive)
        directive_age = active_directive.age(iteration) if active_directive else None
        self.logging("directive_age", directive_age, save_trace=True)
        if active_directive:
            self.logging("directive", active_directive.to_dict(), save_trace=True, print_log=False)
            self.logging("directive_text", directive_text, save_trace=True, print_log=False)

        im_start_time = time.time()
        (
            predicted_observation_30_ticks,
            actions,
            request_background,
            background_reason,
            im_think,
            im_chat_history,
        ) = self.im_agent.run(
            obs_text,
            directive_text=directive_text,
            verifier=self.verify_actions,
        )
        self.logging("im_latency", round(time.time() - im_start_time, 4), save_trace=True)
        self.logging("predicted_observation_30_ticks", predicted_observation_30_ticks, save_trace=True, print_log=False)
        self.logging("request_background", request_background, save_trace=True)
        self.logging("background_reason", background_reason, save_trace=True)
        self.logging("actions", actions, save_trace=True)
        self.logging("im_think", im_think, save_trace=True, print_log=False)
        self.logging("im_chat_history", im_chat_history, save_trace=True, print_log=False)

        await self.run_actions(actions)

        await self._maybe_start_bm(
            iteration=iteration,
            obs_text=obs_text,
            actions=actions,
            request_background=request_background,
            background_reason=background_reason,
            directive_before_im=active_directive,
            latest_directive=latest_directive,
        )
