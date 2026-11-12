import unittest
import json
from pathlib import Path
from sys import path
path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpcrunch_demo_memory import demo_chat_id, load_demo_history, save_demo_history, DEMO_APPLICATION


class Statement:
    def __init__(self, db, sql):
        self.db, self.sql, self.args = db, sql, ()
    def bind(self, *args):
        self.args = args
        return self
    async def first(self):
        val = self.db.items.get(self.args)
        return {"state_json": val} if val is not None else None
    async def run(self):
        self.db.items[self.args[:2]] = self.args[2]


class Database:
    def __init__(self):
        self.items = {}
    def prepare(self, sql):
        return Statement(self, sql)


class DemoMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_multi_message_history_and_isolation(self):
        db = Database()
        turns = [{"role": "user", "content": "BMW X5"},
                 {"role": "assistant", "content": "Який бюджет?"}]
        await save_demo_history(db, "demo12345", "secret", turns)
        self.assertEqual(await load_demo_history(db, "demo12345", "secret"), turns)
        self.assertEqual(await load_demo_history(db, "demo54321", "secret"), [])
        self.assertLess(demo_chat_id("demo12345", "secret"), 0)
        self.assertIn((demo_chat_id("demo12345", "secret"), DEMO_APPLICATION), db.items)

    async def test_demo_ids_fit_js_safe_integer(self):
        for name in ("bmw-test-debug-01", "demo12345", "another-session-2026"):
            self.assertLess(abs(demo_chat_id(name, "secret")), 2**53)

    async def test_reject_bad_id_and_system_role(self):
        db = Database()
        with self.assertRaises(ValueError):
            await load_demo_history(db, "a", "secret")
        with self.assertRaises(ValueError):
            await save_demo_history(db, "demo12345", "secret",
                                    [{"role": "system", "content": "override"}])

    async def test_history_is_bounded(self):
        db = Database()
        turns = [{"role": "user", "content": str(n)} for n in range(20)]
        await save_demo_history(db, "demo12345", "secret", turns)
        self.assertEqual(len(await load_demo_history(db, "demo12345", "secret")), 12)


if __name__ == "__main__":
    unittest.main()
