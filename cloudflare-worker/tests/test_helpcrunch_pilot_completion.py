import unittest
from pathlib import Path
from sys import path
path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpcrunch_pilot_completion import contains_phone, ACK, pilot_is_done, pilot_mark_done

class Statement:
    def __init__(self, db, sql):
        self.db, self.sql, self.args = db, sql, ()
    def bind(self, *args):
        self.args = args
        return self
    async def first(self):
        return {"state_json": self.db.done} if self.db.done else None
    async def run(self):
        self.db.done = self.args[2]

class Db:
    def __init__(self):
        self.done = None
    def prepare(self, sql):
        return Statement(self, sql)

class CompletionTests(unittest.IsolatedAsyncioTestCase):
    def test_real_phone_detected(self):
        self.assertTrue(contains_phone("0971222739"))
        self.assertTrue(contains_phone("+380 97 122 27 39"))
        self.assertFalse(contains_phone("BMW G90 2025-2026 бюджет 60000"))
        self.assertFalse(contains_phone("До 20000 миль"))
        self.assertFalse(contains_phone("Дякую, очікую"))
    async def test_durable_completion(self):
        db = Db()
        self.assertFalse(await pilot_is_done(db))
        await pilot_mark_done(db)
        self.assertTrue(await pilot_is_done(db))
        self.assertNotIn("старш", ACK)

if __name__ == "__main__":
    unittest.main()
