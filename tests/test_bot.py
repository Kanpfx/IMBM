import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from ares import AresBot
from sc2.data import Race, Result, Status
from sc2.main import _host_game, _play_game_ai
from sc2.player import Bot
from sc2.protocol import ProtocolError
from game.bot.main import WhyBot
from unittest.mock import AsyncMock, Mock, call, patch
from ares.consts import UnitRole


class RealtimeEndTests(unittest.IsolatedAsyncioTestCase):
    def make_bot(self, realtime=True, status=Status.in_game):
        bot = object.__new__(WhyBot)
        bot.realtime = realtime
        bot.client = SimpleNamespace(
            _status=status, _game_result=None, game_step=4, leave=AsyncMock()
        )

        async def final_observation(*_args):
            bot.client._status = Status.ended
            bot.client._game_result = {1: Result.Victory}

        bot.client.observation = AsyncMock(side_effect=final_observation)
        return bot

    async def test_known_end_skips_actions_and_fetches_real_result(self):
        bot = self.make_bot(status=Status.ended)
        with patch.object(AresBot, "_after_step", new_callable=AsyncMock) as submit:
            self.assertEqual(await bot._after_step(), 0)
        submit.assert_not_awaited()
        bot.client.observation.assert_awaited_once_with()
        self.assertEqual(bot.client._game_result, {1: Result.Victory})
        bot.client.leave.assert_not_awaited()


    async def test_other_errors_and_non_realtime_still_raise(self):
        for realtime, message in [
            (True, "connection failure"),
            (False, "['Game has already ended']"),
        ]:
            with self.subTest(realtime=realtime, message=message):
                bot = self.make_bot(realtime=realtime)
                with patch.object(AresBot, "_after_step", new_callable=AsyncMock) as submit:
                    submit.side_effect = ProtocolError(message)
                    with self.assertRaises(ProtocolError):
                        await bot._after_step()
                bot.client.observation.assert_not_awaited()

    async def test_realtime_zero_supply_does_not_resign(self):
        bot = self.make_bot()
        bot.supply_used = 0
        bot.opening_chat_tag = True
        bot.llm_controller = SimpleNamespace(run_iteration=AsyncMock())
        with patch.object(AresBot, "on_step", new_callable=AsyncMock):
            await bot.on_step(60)
        bot.client.leave.assert_not_awaited()
        bot.llm_controller.run_iteration.assert_awaited_once_with(bot, 60)


    async def test_host_finishes_with_actual_result_and_saves_replay(self):
        bot = self.make_bot()
        client = bot.client
        state = SimpleNamespace(observation=SimpleNamespace(
            observation=SimpleNamespace(game_loop=0)
        ))

        async def observe(*_args):
            if client._status == Status.ended:
                client._game_result = {1: Result.Victory}
            return state

        async def submit():
            client._status = Status.ended
            raise ProtocolError("['Game has already ended']")

        client.observation = AsyncMock(side_effect=observe)
        client.get_game_data = AsyncMock()
        client.get_game_info = AsyncMock()
        client.ping = AsyncMock(return_value=SimpleNamespace(ping=SimpleNamespace(base_build=1)))
        client._execute = AsyncMock()
        client.save_replay_path = "match.SC2Replay"
        client.save_replay = AsyncMock()
        client.quit = AsyncMock()
        bot._initialize_variables = MagicMock()
        bot._prepare_start = MagicMock()
        bot._prepare_step = AsyncMock()
        bot._prepare_first_step = MagicMock()
        bot.on_before_start = AsyncMock()
        bot.on_start = AsyncMock()
        bot.issue_events = AsyncMock()
        bot.on_step = AsyncMock()
        bot.llm_controller = SimpleNamespace(telemetry=MagicMock(), close=AsyncMock())
        bot._result_metadata = lambda result: {"result": result.name}
        bot.on_end = AsyncMock(wraps=bot.on_end)
        process = MagicMock()
        process.__aenter__.return_value = SimpleNamespace(ping=AsyncMock())

        async def play(*_args):
            return await _play_game_ai(client, 1, bot, True, None)

        with (
            patch("sc2.main.SC2Process", return_value=process),
            patch("sc2.main._setup_host_game", new=AsyncMock(return_value=client)),
            patch("sc2.main._play_game", new=AsyncMock(side_effect=play)),
            patch("sc2.main.GameState", return_value=SimpleNamespace(
                game_loop=0, score=SimpleNamespace(score=0)
            )),
            patch.object(AresBot, "_after_step", new=AsyncMock(side_effect=submit)),
            patch.object(AresBot, "on_end", new_callable=AsyncMock),
        ):
            result = await _host_game(None, [Bot(Race.Terran, bot)], realtime=True)

        self.assertEqual(result, Result.Victory)
        bot.on_end.assert_awaited_once_with(Result.Victory)
        metadata = bot.llm_controller.telemetry.update_metadata.call_args.kwargs
        self.assertEqual(metadata["result"], "Victory")
        self.assertIn("completed_at", metadata)
        client.save_replay.assert_awaited_once_with("match.SC2Replay")
        client.leave.assert_awaited_once()
        client.quit.assert_awaited_once()


class RepairTests(unittest.TestCase):
    def test_all_invalid_workers_are_released_in_one_update(self):
        injured = SimpleNamespace(health_percentage=0.5)
        low_health = SimpleNamespace(health_percentage=0.2)
        healthy = SimpleNamespace(health_percentage=0.4)
        bot = SimpleNamespace(
            injured_general_unit_to_repairing_scvs={100: {1, 2, 3, 4}},
            unit_tag_dict={100: injured, 2: low_health, 4: healthy},
            mediator=Mock(),
            _scvs_to_general_repair_logic=Mock(),
        )

        WhyBot._execute_scv_to_general_repair(bot)

        self.assertEqual(bot.injured_general_unit_to_repairing_scvs, {100: {4}})
        bot.mediator.assign_role.assert_called_once_with(
            tag=2, role=UnitRole.GATHERING
        )
        bot._scvs_to_general_repair_logic.assert_called_once_with(injured, [healthy])

    def test_finished_and_missing_targets_release_their_workers(self):
        bot = SimpleNamespace(
            injured_general_unit_to_repairing_scvs={100: {1}, 200: {2}},
            unit_tag_dict={100: SimpleNamespace(health_percentage=1.0)},
            mediator=Mock(),
            _scvs_to_general_repair_logic=Mock(),
        )

        WhyBot._execute_scv_to_general_repair(bot)

        self.assertEqual(bot.injured_general_unit_to_repairing_scvs, {})
        bot.mediator.batch_assign_role.assert_has_calls([
            call(tags={1}, role=UnitRole.GATHERING),
            call(tags={2}, role=UnitRole.GATHERING),
        ])
        bot.mediator.assign_role.assert_called_once_with(
            tag=100, role=UnitRole.ATTACKING
        )
        bot._scvs_to_general_repair_logic.assert_not_called()


class ConstructionCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_critically_damaged_unfinished_buildings_are_cancelled(self):
        for is_structure, is_ready, health, expected in [
            (False, True, 10, False),
            (True, True, 10, False),
            (True, False, 10, True),
            (True, False, 90, False),
        ]:
            with self.subTest(
                is_structure=is_structure, is_ready=is_ready, health=health
            ):
                bot = object.__new__(WhyBot)
                bot.manager_hub = SimpleNamespace(manager_mediator=Mock())
                unit = SimpleNamespace(
                    is_structure=is_structure,
                    is_ready=is_ready,
                    health=health,
                    health_max=1000,
                )
                with patch.object(
                    AresBot, "on_unit_took_damage", new_callable=AsyncMock
                ) as parent:
                    await bot.on_unit_took_damage(unit, 5)
                parent.assert_awaited_once_with(unit, 5)
                if expected:
                    bot.mediator.cancel_structure.assert_called_once_with(structure=unit)
                else:
                    bot.mediator.cancel_structure.assert_not_called()
