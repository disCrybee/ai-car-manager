import unittest
from pathlib import Path
from sys import path
path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpcrunch_budget_guard import fresh_consultation, low_usd_budget_reply

class BudgetGuardTests(unittest.TestCase):
    def test_fresh_greeting_resets_old_car(self):
        self.assertTrue(fresh_consultation("Добрий день, цікавить авто в бюджет 8.000$"))
        self.assertTrue(fresh_consultation("Добрий день! Цікавить Rolls-Royce Cullinan"))
        self.assertFalse(fresh_consultation("А якщо кросовер?"))
    def test_low_usd_budget_while_no_currency_inference(self):
        reply = low_usd_budget_reply("Добрий день, цікавить авто в бюджет 8.000$")
        self.assertIsNotNone(reply)
        self.assertIn("дуже обмеженим", reply)
        self.assertIn("$10 000", reply)
        self.assertNotIn("тип — седан", reply)
        self.assertIsNone(low_usd_budget_reply("Бюджет до 8.000"))
        self.assertIsNone(low_usd_budget_reply("Бюджет $12 000"))

if __name__ == "__main__":
    unittest.main()
