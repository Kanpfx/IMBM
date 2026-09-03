import sys
import unittest
from unittest.mock import patch

from run import parse_args


class RunArgumentTests(unittest.TestCase):
    def test_removed_bm_flags_are_rejected(self):
        for flag in ("-bm", "--bm", "--enable_bm"):
            with self.subTest(flag=flag), patch.object(
                sys, "argv", ["run.py", "--map_name", "TestMap", flag]
            ):
                with self.assertRaises(SystemExit):
                    parse_args()

    def test_build_mode_and_tactic_are_explicit_arguments(self):
        with patch.object(
            sys,
            "argv",
            [
                "run.py",
                "--map_name",
                "TestMap",
                "--build_mode",
                "Macro",
                "--tactic",
                "ThorDrop",
            ],
        ):
            args = parse_args()
            self.assertEqual(args.build_mode, "Macro")
            self.assertEqual(args.tactic, "ThorDrop")

    def test_default_tactic_preserves_current_behavior(self):
        with patch.object(sys, "argv", ["run.py", "--map_name", "TestMap"]):
            args = parse_args()
            self.assertEqual(args.build_mode, "RandomBuild")
            self.assertEqual(args.tactic, "BattleCruiserRush")
