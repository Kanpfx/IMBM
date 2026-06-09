import asyncio
import time

from agents import BmAgent, ImAgent
from core.base_player import BasePlayer
from core.economy import EconomyMixin
from runtime.action_queue import ActionQueueStore, QUEUE_NAMES, WAITING
from sc2.ids.unit_typeid import UnitTypeId


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
        self.im_agents = {
            queue_name: ImAgent(config.own_race, **im_agent_config)
            for queue_name in QUEUE_NAMES
        }

        self.enable_bm = enable_bm
        self.bm_agent = None
        if enable_bm:
            bm_agent_config = {
                "model_name": bm_model_name,
                "generation_config": bm_generation_config,
                "llm_client": bm_llm_client,
            }
            self.bm_agent = BmAgent(config.own_race, **bm_agent_config)

        self.action_queue_store = ActionQueueStore()
        self.bm_minerals_threshold = 100
        self.queue_pressure_limit = 5
        self.bm_resume_queue_limit = 2
        self._bm_paused_by_queue_pressure = False
        self._bm_task = None

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

    def _should_run_bm(self) -> bool:
        return (
            self.enable_bm
            and self.bm_agent is not None
            and self.minerals > self.bm_minerals_threshold
        )

    def _bm_strategic_suggestions(self) -> list[str]:
        suggestions = []

        if self.minerals >= 500:
            suggestions.append("Minerals are high; prefer tasks that spend resources on economy, production, or useful tech.")

        if self.townhalls.exists and self.supply_workers < self.townhalls.amount * 16:
            suggestions.append("Worker count is below base saturation; keep worker production in mind if a base can train workers.")

        if self.supply_left <= 3 and self.supply_cap < 200:
            suggestions.append("Supply is tight; consider supply capacity before a block.")

        if self.supply_army == 0 and not self.enemy_units.exists:
            suggestions.append("No army and no visible enemy threat; prefer economy or production tasks over generic map activity.")

        if self.config.own_race == "Terran":
            supply_depots = self.get_total_amount(UnitTypeId.SUPPLYDEPOT)
            barracks = self.get_total_amount(UnitTypeId.BARRACKS)
            refineries = self.get_total_amount(UnitTypeId.REFINERY)

            if supply_depots < 1:
                suggestions.append("No Supply Depot is present or pending; basic supply infrastructure is an early bottleneck.")
            if refineries < 1 and self.minerals >= 75:
                suggestions.append("No Refinery is present or pending; gas access may be needed for future tech.")
            if barracks < 1:
                if supply_depots < 1:
                    suggestions.append("No Barracks yet; it normally comes after a Supply Depot unlocks infantry production.")
                else:
                    suggestions.append("No Barracks is present or pending; infantry production is not unlocked yet.")

        for queue_name in QUEUE_NAMES:
            waiting_count = sum(
                1
                for task in self.action_queue_store.queues.get(queue_name, [])
                if task.get("status") == WAITING and task.get("task")
            )
            if waiting_count:
                suggestions.append(
                    f"{queue_name} already has {waiting_count} waiting task(s); append only if the new task is more specific or covers a different immediate need."
                )

        return suggestions[:8]

    async def _run_bm_blocking(self, iteration: int, obs_text: str) -> None:
        start_time = time.time()
        try:
            loop = asyncio.get_running_loop()
            strategic_suggestions = self._bm_strategic_suggestions()
            append_items, bm_think, bm_chat_history = await loop.run_in_executor(
                None,
                lambda: self.bm_agent.run(
                    obs_text=obs_text,
                    action_queues=self.action_queue_store.snapshot(),
                    blocked_feedback=self.action_queue_store.feedback_snapshot(),
                    strategic_suggestions=strategic_suggestions,
                ),
            )
            accepted = self.action_queue_store.append_tasks(append_items)
            self.logging("bm_latency", round(time.time() - start_time, 4), save_trace=True)
            self.logging("bm_strategic_suggestions", strategic_suggestions, save_trace=True, print_log=False)
            self.logging("bm_append_items", append_items, save_trace=True)
            self.logging("bm_accepted_items", accepted, save_trace=True)
            self.logging("bm_think", bm_think, save_trace=True, print_log=False)
            self.logging("bm_chat_history", bm_chat_history, save_trace=True, print_log=False)
            self.logging("action_queues", self.action_queue_store.snapshot(), save_trace=True)
        except Exception as exc:
            self.logging("bm_error", str(exc), level="error", save_trace=True)

    def _clear_finished_bm_task(self) -> None:
        if self._bm_task is not None and self._bm_task.done():
            self._bm_task = None

    def _queue_pressure_allows_bm(self, iteration: int) -> bool:
        if self._bm_paused_by_queue_pressure:
            if self.action_queue_store.has_queue_pressure(self.bm_resume_queue_limit):
                if iteration % 60 == 0:
                    self.logging(
                        "bm_skip_reason",
                        f"BM paused until all action queues have at most {self.bm_resume_queue_limit} task.",
                        save_trace=True,
                    )
                return False
            self._bm_paused_by_queue_pressure = False
            self.logging("bm_pressure_resumed", self.action_queue_store.snapshot(), save_trace=True)

        if self.action_queue_store.has_queue_pressure(self.queue_pressure_limit):
            self._bm_paused_by_queue_pressure = True
            self.logging(
                "bm_skip_reason",
                (
                    f"Action queue length exceeded pressure limit {self.queue_pressure_limit}; "
                    f"BM will resume when every queue has at most {self.bm_resume_queue_limit} task."
                ),
                save_trace=True,
            )
            return False

        return True

    async def _schedule_bm_if_ready(self, iteration: int) -> None:
        self._clear_finished_bm_task()

        if not self._should_run_bm():
            return

        if self._bm_task is not None:
            return

        if not self._queue_pressure_allows_bm(iteration):
            return

        obs_text = await self.obs_to_text(log_prefix="bm_")
        self._bm_task = asyncio.create_task(self._run_bm_blocking(iteration, obs_text))
        self.logging("bm_scheduled", iteration, save_trace=True)

    async def _run_im_for_queue(self, queue_name: str, task: dict, obs_text: str):
        loop = asyncio.get_running_loop()
        actions, im_think, im_chat_history = await loop.run_in_executor(
            None,
            lambda: self.im_agents[queue_name].run(
                queue_name=queue_name,
                obs_text=obs_text,
                task=task,
                verifier=self.verify_actions,
            ),
        )
        return queue_name, task, actions, im_think, im_chat_history

    async def _run_parallel_im(self) -> list:
        waiting_tasks = [
            (queue_name, self.action_queue_store.first_waiting(queue_name))
            for queue_name in QUEUE_NAMES
        ]
        waiting_tasks = [
            (queue_name, task)
            for queue_name, task in waiting_tasks
            if task is not None
        ]
        if not waiting_tasks:
            return []

        im_inputs = []
        for queue_name, task in waiting_tasks:
            obs_text = await self.obs_to_text(log_prefix=f"{queue_name}_")
            im_inputs.append((queue_name, task, obs_text))

        im_tasks = [
            self._run_im_for_queue(queue_name, task, obs_text)
            for queue_name, task, obs_text in im_inputs
        ]
        results = await asyncio.gather(*im_tasks, return_exceptions=True)

        valid_actions = []
        for result in results:
            if isinstance(result, Exception):
                self.logging("im_error", str(result), level="error", save_trace=True)
                continue

            queue_name, task, actions, im_think, im_chat_history = result
            self.logging(f"{queue_name}_task", task, save_trace=True)
            self.logging(f"{queue_name}_actions", actions, save_trace=True)
            self.logging(f"{queue_name}_im_think", im_think, save_trace=True, print_log=False)
            self.logging(f"{queue_name}_im_chat_history", im_chat_history, save_trace=True, print_log=False)

            if not actions:
                outcome = self.action_queue_store.mark_blocked(
                    queue_name,
                    task["task"],
                    "IM returned no executable actions.",
                )
                self.logging(f"{queue_name}_blocked_outcome", outcome, save_trace=True)
                continue

            ok, verification_message = self.verify_actions(actions)
            if not ok:
                outcome = self.action_queue_store.mark_blocked(
                    queue_name,
                    task["task"],
                    verification_message,
                )
                self.logging(f"{queue_name}_blocked_reason", verification_message, save_trace=True)
                self.logging(f"{queue_name}_blocked_outcome", outcome, save_trace=True)
                continue

            self.action_queue_store.mark_done(queue_name, task["task"])
            for action in actions:
                if isinstance(action, dict):
                    action["_source_queue"] = queue_name
            valid_actions.extend(actions)

        self.logging("action_queues", self.action_queue_store.snapshot(), save_trace=True)
        return valid_actions

    async def run(self, iteration: int):
        await self._auto_micro()

        if iteration % 10 == 0:
            self.log_current_iteration(iteration)

        await self._schedule_bm_if_ready(iteration)

        if not self.action_queue_store.has_waiting_tasks():
            return

        im_start_time = time.time()
        actions = await self._run_parallel_im()
        self.logging("im_total_latency", round(time.time() - im_start_time, 4), save_trace=True)
        self.logging("merged_actions", actions, save_trace=True)

        if actions:
            await self.run_actions(actions)
