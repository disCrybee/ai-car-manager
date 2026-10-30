import unittest
from pathlib import Path
from sys import path

path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpcrunch_store import commit_dialog_event


class Statement:
    def __init__(self, db, sql):
        self.db, self.sql, self.args = db, sql, ()
    def bind(self, *args):
        self.args = args
        return self
    async def first(self):
        return {"event_key": self.args[0]} if self.args[0] in self.db.events else None


class D1:
    def __init__(self, fail=False):
        self.events = set()
        self.state = {}
        self.fail = fail
    def prepare(self, sql):
        return Statement(self, sql)
    async def batch(self, statements):
        if self.fail:
            raise RuntimeError("database write failed")
        key, chat, app = statements[0].args
        if key in self.events:
            raise RuntimeError("UNIQUE constraint failed")
        self.events.add(key)
        self.state[(chat, app)] = statements[1].args[2]


class AtomicStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_event_commits(self):
        db = D1()
        self.assertTrue(await commit_dialog_event(db, "9:1:10", 1, 9, {"pending_field": "budget"}))
        self.assertIn((1, 9), db.state)

    async def test_duplicate_keeps_state(self):
        db = D1()
        await commit_dialog_event(db, "9:1:10", 1, 9, {"answer": "first"})
        self.assertFalse(await commit_dialog_event(db, "9:1:10", 1, 9, {"answer": "second"}))
        self.assertIn("first", db.state[(1, 9)])

    async def test_failure_preserves_retry(self):
        db = D1(fail=True)
        with self.assertRaises(RuntimeError):
            await commit_dialog_event(db, "9:1:10", 1, 9, {"answer": "first"})
        self.assertEqual(db.events, set())
        db.fail = False
        self.assertTrue(await commit_dialog_event(db, "9:1:10", 1, 9, {"answer": "first"}))


if __name__ == "__main__":
    unittest.main()
