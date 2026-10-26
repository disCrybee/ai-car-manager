import unittest
from pathlib import Path
from sys import path
path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpcrunch_pilot_completion import contains_phone, ACK, pilot_is_done, pilot_mark_done, is_new_vehicle_request, is_substantive_followup, pilot_clear_done

class Statement:
    def __init__(self, db, sql):
        self.db, self.sql, self.args = db, sql, ()
    def bind(self, *args):
        self.args = args
        return self
    async def first(self):
        return {"state_json": self.db.done} if self.db.done else None
    async def run(self):
        self.db.done = None if self.sql.startswith('DELETE') else self.args[2]

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
    def test_new_vehicle_restarts_but_thanks_does_not(self):
        self.assertTrue(is_new_vehicle_request("Tesla model S Plaid"))
        self.assertTrue(is_new_vehicle_request("Цікавить Audi Q7"))
        self.assertTrue(is_new_vehicle_request("Добрий день, цікавить Rolls Royce Cullinan"))
        self.assertTrue(is_new_vehicle_request("Цікавить нова модель невідомої марки"))
        self.assertFalse(is_new_vehicle_request("Дякую, очікую"))
        self.assertFalse(is_new_vehicle_request("0971222739"))

    def test_substantive_followup_after_phone(self):
        self.assertTrue(is_substantive_followup("А скільки буде вартувати доставка?"))
        self.assertTrue(is_substantive_followup("Tesla Model S Plaid"))
        self.assertFalse(is_substantive_followup("Дякую, очікую"))
        self.assertFalse(is_substantive_followup("Дякую!"))
        self.assertTrue(is_substantive_followup("Підкажіть, які у вас умови?"))
        self.assertTrue(is_substantive_followup("Rolls Royce Cullinan"))
        self.assertTrue(is_substantive_followup("Мені потрібна допомога з доставкою"))

    async def test_durable_completion(self):
        db = Db()
        self.assertFalse(await pilot_is_done(db))
        await pilot_mark_done(db)
        self.assertTrue(await pilot_is_done(db))
        await pilot_clear_done(db)
        self.assertFalse(await pilot_is_done(db))
        self.assertNotIn("старш", ACK)

if __name__ == "__main__":
    unittest.main()
