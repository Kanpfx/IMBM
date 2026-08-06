import unittest

from core.phase import PhaseResolver
from knowledge.loader import load_battlecruiser_tactic


class PhaseResolverTests(unittest.TestCase):
    def test_tactic_phase_ids_match_runtime_phase_ids(self):
        tactic = load_battlecruiser_tactic()

        self.assertEqual(
            [phase["id"] for phase in tactic["phases"]],
            [
                "opening_factory",
                "opening_air_tech",
                "first_battlecruiser",
                "bc_pressure",
            ],
        )

    def test_battlecruiser_phase_progression_is_deterministic(self):
        resolver = PhaseResolver()
        self.assertEqual(resolver.resolve({}).id, "opening_factory")
        self.assertEqual(
            resolver.resolve({"pending:FACTORY": 1}).id, "opening_air_tech"
        )
        self.assertEqual(
            resolver.resolve(
                {"FACTORY": 1, "STARPORT": 1, "FUSIONCORE": 1, "STARPORTTECHLAB": 1}
            ).id,
            "first_battlecruiser",
        )
        self.assertEqual(resolver.resolve({"BATTLECRUISER": 1}).id, "bc_pressure")

    def test_phase_revision_only_changes_on_transition(self):
        resolver = PhaseResolver()
        first = resolver.resolve({})
        repeat = resolver.resolve({})
        changed = resolver.resolve({"FACTORY": 1})
        self.assertEqual(first.revision, repeat.revision)
        self.assertEqual(changed.revision, first.revision + 1)

    def test_phase_does_not_move_backwards_after_a_loss(self):
        resolver = PhaseResolver()
        resolver.resolve({"BATTLECRUISER": 1})
        self.assertEqual(resolver.resolve({}).id, "bc_pressure")
