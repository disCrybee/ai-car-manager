"""Validate the actual staging D1 schema using SQLite in CI.

Cloudflare D1 uses SQLite; no Cloudflare credentials or customer data needed.
"""
import sqlite3
import unittest
from pathlib import Path


class HelpCrunchSchemaTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        script = (Path(__file__).resolve().parents[1]
                  / "migrations/helpcrunch/0001_dialog_state.sql").read_text()
        self.db.executescript(script)

    def tearDown(self):
        self.db.close()

    def test_schema_is_repeatable(self):
        script = (Path(__file__).resolve().parents[1]
                  / "migrations/helpcrunch/0001_dialog_state.sql").read_text()
        self.db.executescript(script)

    def test_distinct_chat_and_application(self):
        self.db.execute(
            "INSERT INTO hc_dialog_state(chat_id,application_id,state_json) VALUES(?,?,?)",
            (100, 8, '{"pending_field":"budget"}')
        )
        self.db.execute(
            "INSERT INTO hc_dialog_state(chat_id,application_id,state_json) VALUES(?,?,?)",
            (100, 9, '{"pending_field":"mileage"}')
        )
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM hc_dialog_state WHERE chat_id=100").fetchone()[0],
            2
        )

    def test_event_deduplication_unique_key(self):
        self.db.execute(
            "INSERT INTO hc_processed_events(event_key,chat_id,application_id) VALUES(?,?,?)",
            ("8:100:7", 100, 8)
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "INSERT INTO hc_processed_events(event_key,chat_id,application_id) VALUES(?,?,?)",
                ("8:100:7", 100, 8)
            )

    def test_event_state_transaction_rolls_back(self):
        self.db.execute("BEGIN")
        self.db.execute(
            "INSERT INTO hc_processed_events(event_key,chat_id,application_id) VALUES(?,?,?)",
            ("8:100:7", 100, 8)
        )
        self.db.execute(
            "INSERT INTO hc_dialog_state(chat_id,application_id,state_json) VALUES(?,?,?)",
            (100, 8, '{"pending_field":"budget"}')
        )
        self.db.rollback()
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM hc_processed_events").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM hc_dialog_state").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
