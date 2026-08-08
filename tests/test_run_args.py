import sys
import unittest
from unittest.mock import patch

from run import parse_args


class RunArgumentTests(unittest.TestCase):
    def test_all_bm_flag_aliases_use_enable_bm_destination(self):
        for flag in ("-bm", "--bm", "--enable_bm"):
            with self.subTest(flag=flag), patch.object(
                sys, "argv", ["run.py", "--map_name", "TestMap", flag]
            ):
                args = parse_args()
                self.assertTrue(args.enable_bm)

    def test_bm_is_disabled_without_a_flag(self):
        with patch.object(sys, "argv", ["run.py", "--map_name", "TestMap"]):
            args = parse_args()
            self.assertFalse(args.enable_bm)
