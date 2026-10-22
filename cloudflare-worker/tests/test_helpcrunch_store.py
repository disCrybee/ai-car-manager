import unittest
from pathlib import Path
from sys import path

path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpcrunch_store import _positive_int, save_dialog, claim_event


class FakeDb:
    def __init__(self):
        self.sql = ""
        self.args = ()
        self.inserted = set()

    def prepare(self, sql):
        self.sql = sql
        return self

    def bind(self, *args):
        self.args = args
        return self

    async def run(self):
        if "INSERT OR IGNORE" in self.sql:
            key = self.args[0]
            new = key not in self.inserted
            self.inserted.add(key)
            return {"meta": {"changes": int(new)}}
        return {"meta": {"changes": 1}}


class StoreTests(unittest.IsolatedAsyncioTestCase):
    def test_ids_validation(self):
        with self.assertRaises(ValueError):
            _positive_int(0, "chat_id")

    async def test_state_scoped_to_chat_and_app(self):
        db = FakeDb()
        await save_dialog(db, 60311, 71, {"pending_field": "mileage"})
        self.assertEqual(db.args[:2], (60311, 71))
        self.assertIn("pending_field", db.args[2])

    async def test_event_claim_is_idempotent(self):
        db = FakeDb()
        self.assertTrue(await claim_event(db, "msg:100", 60311, 71))
        self.assertFalse(await claim_event(db, "msg:100", 60311, 71))
        self.assertTrue(await claim_event(db, "msg:101", 60311, 71))


if __name__ == "__main__":
    unittest.main()
