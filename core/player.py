from players.llm_player import LLMPlayer
from agents import ImAgent, BmAgent
from runtime.directive import Directive, DirectiveStore
from sc2.ids.unit_typeid import UnitTypeId

import asyncio
import time
import random


class ImBmPlayer(LLMPlayer):
    """IM/BM dual-model player. Inherits all SunTzu logic (economy, suggestions,
    logging, auto-micro, decision gating) from LLMPlayer. Only overrides agent
    setup and the main run loop with the IM/BM async pipeline."""

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
        # Skip LLMPlayer.__init__ — call BasePlayer directly, then set up
        # our own agents instead of plan_agent/action_agent.
        from players.base_player import BasePlayer
        BasePlayer.__init__(self, config, *args, **kwargs)

        # ── IM Agent (replaces plan_agent + action_agent) ──
        im_agent_config = {
            "model_name": self.model_name,
            "generation_config": self.generation_config,
            "llm_client": self.llm_client,
        }
        self.im_agent = ImAgent(config.own_race, **im_agent_config)

        # ── BM Agent (optional, replaces PlanVerifier's role) ──
        self.enable_bm = enable_bm
        self.bm_agent = None
        if enable_bm:
            bm_agent_config = {
                "model_name": bm_model_name,
                "generation_config": bm_generation_config,
                "llm_client": bm_llm_client,
            }
            self.bm_agent = BmAgent(config.own_race, **bm_agent_config)

        # ── DirectiveStore (IM↔BM communication) ──
        self.directive_store = DirectiveStore()

        # ── BM async state ──
        self.bm_task = None
        self.bm_task_reason = ""
        self.directive_ttl = 360

        # ── Inherited from LLMPlayer (must duplicate — not calling LLMPlayer.__init__) ──
        self.next_decision_time = -1
        self.scv_auto_attack_distance = 4
        self.scv_auto_attack_time = 240

    # ═══════════════════════════════════════════════════════════════
    # IMBM: Directive → plan text conversion
    # ═══════════════════════════════════════════════════════════════

    def _directive_to_plan_text(self, directive: Directive | None) -> str | None:
        """Convert BM plan list to SunTzu-style 'Given Tasks' ordered list."""
        if directive is None or not directive.data:
            return None
        items = [f"{i+1}. {cmd}" for i, cmd in enumerate(directive.data)]
        return "### Given Tasks\n" + "\n".join(items)

    # ═══════════════════════════════════════════════════════════════
    # IMBM: BM async scheduling
    # ═══════════════════════════════════════════════════════════════

    def _active_bm_task(self) -> bool:
        return self.bm_task is not None and not self.bm_task.done()

    def _current_iteration(self, fallback: int) -> int:
        try:
            return self.state.game_loop // 4
        except Exception:
            return fallback

    async def _run_bm_background(self, obs_text: str, iteration: int, trigger_reason: str):
        start_time = time.time()
        try:
            loop = asyncio.get_running_loop()
            suggestions = self.get_suggestions()
            plan_data, bm_think, bm_chat_history = await loop.run_in_executor(
                None,
                lambda: self.bm_agent.run(
                    obs_text=obs_text,
                    background_request=trigger_reason,
                    suggestions=suggestions,
                ),
            )
            issued_at_tick = iteration
            valid_until_tick = issued_at_tick + self.directive_ttl
            directive = Directive(
                data=plan_data,
                issued_at_tick=issued_at_tick,
                valid_until_tick=valid_until_tick,
                source="BM",
            )
            self.directive_store.write(directive)
            self.logging("bm_latency", round(time.time() - start_time, 4), save_trace=True)
            self.logging("bm_trigger_reason", trigger_reason, save_trace=True)
            self.logging("bm_plan", plan_data, save_trace=True)
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

        self.logging("bm_triggered", True, save_trace=True)
        self.logging("bm_trigger_reason", trigger_reason, save_trace=True)
        self.bm_task_reason = trigger_reason
        self.bm_task = asyncio.create_task(
            self._run_bm_background(
                obs_text=obs_text,
                iteration=iteration,
                trigger_reason=trigger_reason,
            )
        )

    # ═══════════════════════════════════════════════════════════════
    # Main run loop — overrides LLMPlayer.run()
    # Keeps SunTzu auto_micro + decision gating unchanged.
    # Replaces plan_agent→action_agent with im_agent + BM async.
    # ═══════════════════════════════════════════════════════════════

    async def run(self, iteration: int):
        # ── Auto micro (inherited from LLMPlayer pattern, same logic) ──
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
                near_by_enemies = self.enemy_units.closer_than(self.scv_auto_attack_distance, unit.position)
                near_by_enemies = near_by_enemies.closer_than(self.scv_auto_attack_distance, self.start_location)
                target_enemy = self.get_lowest_health_enemy(near_by_enemies)
                if unit.type_id in [UnitTypeId.SCV] and self.time < self.scv_auto_attack_time and target_enemy:
                    unit.attack(target_enemy)

        # ── SunTzu decision gating (unchanged) ──
        if self.config.enable_random_decision_interval:
            decision_iteration = random.randint(24, 36)
            decision_minerals = random.randint(130, 200)
        else:
            decision_iteration = 30
            decision_minerals = 170

        if (
            iteration % decision_iteration == 0
            and self.minerals >= decision_minerals
            or iteration == self.next_decision_time
        ):
            self.next_decision_time = iteration + 9 * decision_iteration

            self.log_current_iteration(iteration)
            obs_text = await self.obs_to_text()

            # ── IMBM: read BM directive ──
            latest_directive = self.directive_store.latest()
            active_directive = self.directive_store.read(iteration)
            plan_text = self._directive_to_plan_text(active_directive)
            directive_age = active_directive.age(iteration) if active_directive else None
            self.logging("directive_age", directive_age, save_trace=True)
            if active_directive:
                self.logging("directive", active_directive.to_dict(), save_trace=True, print_log=False)
                self.logging("plan_text", plan_text, save_trace=True, print_log=False)

            # ── IMBM: IM agent (replaces plan_agent + action_agent) ──
            im_start_time = time.time()
            (
                predicted_observation,
                actions,
                request_background,
                background_reason,
                im_think,
                im_chat_history,
            ) = self.im_agent.run(
                obs_text,
                plan_text=plan_text,
                verifier=self.verify_actions,
            )
            self.logging("im_latency", round(time.time() - im_start_time, 4), save_trace=True)
            self.logging("predicted_observation", predicted_observation, save_trace=True, print_log=False)
            self.logging("request_background", request_background, save_trace=True)
            self.logging("background_reason", background_reason, save_trace=True)
            self.logging("actions", actions, save_trace=True)
            self.logging("im_think", im_think, save_trace=True, print_log=False)
            self.logging("im_chat_history", im_chat_history, save_trace=True, print_log=False)

            # Execute actions (inherited)
            await self.run_actions(actions)

            # ── IMBM: trigger BM if needed ──
            await self._maybe_start_bm(
                iteration=iteration,
                obs_text=obs_text,
                request_background=request_background,
                background_reason=background_reason,
                directive_before_im=active_directive,
                latest_directive=latest_directive,
            )

        elif iteration % 10 == 0:
            self.log_current_iteration(iteration)
