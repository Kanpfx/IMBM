import unittest

from core.phase import PhaseResolver
from knowledge.loader import load_battlecruiser_tactic


class PhaseResolverTests(unittest.TestCase):
    def test_tactic_phase_ids_match_runtime_phase_ids(self):
        tactic = load_battlecruiser_tactic()

        self.assertEqual(
            [phase["id"] for phase in tactic["phases"]],
            [
                "opening_tech",
                "first_bc_preparation",
                "first_bc_transition",
                "bc_pressure",
            ],
        )

    def test_battlecruiser_phase_progression_is_deterministic(self):
        resolver = PhaseResolver()
        self.assertEqual(resolver.resolve({}).id, "opening_tech")
        self.assertEqual(
            resolver.resolve(
                {
                    "ready:FUSIONCORE": 1,
                    "ready:STARPORTTECHLAB": 1,
                }
            ).id,
            "first_bc_preparation",
        )
        self.assertEqual(
            resolver.resolve(
                {
                    "ready:FUSIONCORE": 1,
                    "ready:STARPORTTECHLAB": 1,
                    "pending:BATTLECRUISER": 1,
                }
            ).id,
            "first_bc_transition",
        )
        self.assertEqual(
            resolver.resolve({"BATTLECRUISER": 1, "ready:BATTLECRUISER": 1}).id,
            "bc_pressure",
        )

    def test_unready_bc_technology_does_not_enter_first_bc_phase(self):
        resolver = PhaseResolver()
        phase = resolver.resolve(
            {"FACTORY": 1, "FUSIONCORE": 1, "STARPORTTECHLAB": 1}
        )

        self.assertEqual(phase.id, "opening_tech")

    def test_phase_revision_only_changes_on_transition(self):
        resolver = PhaseResolver()
        first = resolver.resolve({})
        repeat = resolver.resolve({})
        changed = resolver.resolve(
            {"ready:FUSIONCORE": 1, "ready:STARPORTTECHLAB": 1}
        )
        self.assertEqual(first.revision, repeat.revision)
        self.assertEqual(changed.revision, first.revision + 1)

    def test_phase_does_not_move_backwards_after_a_loss(self):
        resolver = PhaseResolver()
        resolver.resolve({"BATTLECRUISER": 1, "ready:BATTLECRUISER": 1})
        self.assertEqual(resolver.resolve({}).id, "bc_pressure")
