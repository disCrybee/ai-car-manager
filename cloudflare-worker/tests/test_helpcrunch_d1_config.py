import unittest
from pathlib import Path
from sys import path

path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare_helpcrunch_d1 import build_config


class D1ConfigTests(unittest.TestCase):
    def setUp(self):
        self.base = {"name": "auction-auto-helpcrunch-test",
                     "main": "src/helpcrunch_test_entry.py"}
        self.uid = "12345678-1234-1234-1234-123456789abc"

    def test_isolated_binding(self):
        config = build_config(self.base, self.uid)
        self.assertEqual(config["d1_databases"][0]["binding"], "HC_DB")
        self.assertEqual(config["d1_databases"][0]["database_id"], self.uid)
        self.assertNotIn("d1_databases", self.base)

    def test_no_legacy_database(self):
        with self.assertRaises(ValueError):
            build_config(self.base, self.uid, self.uid)

    def test_bad_uuid(self):
        with self.assertRaises(ValueError):
            build_config(self.base, "legacy-DB")

    def test_no_accidental_other_worker(self):
        with self.assertRaises(ValueError):
            build_config({"name": "auction-auto-bot", "main": "src/entry.py"}, self.uid)


if __name__ == "__main__":
    unittest.main()
