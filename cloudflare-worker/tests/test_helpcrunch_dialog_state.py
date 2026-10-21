import unittest
from pathlib import Path
from sys import path
path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpcrunch_dialog_state import initial_state, advance


class DialogStateTests(unittest.TestCase):
    def test_budget_currency_followup(self):
        state, question = advance(initial_state(), "Бюджет 700.000")
        self.assertEqual(state["pending_field"], "budget")
        self.assertIsNotNone(question)
        state, question = advance(state, "у гривнях")
        self.assertIsNone(question)
        self.assertIsNone(state["pending_field"])
        self.assertIn("700.000", state["verified"]["budget"])
        self.assertIn("гривнях", state["verified"]["budget"])

    def test_mileage_missing_scale_does_not_confirm(self):
        state, question = advance(initial_state(), "Пробіг до 100")
        self.assertEqual(state["pending_field"], "mileage")
        state, question = advance(state, "км")
        self.assertEqual(state["pending_field"], "mileage")
        self.assertNotIn("mileage", state["verified"])
        self.assertIsNotNone(question)
        state, question = advance(state, "100 тисяч км")
        self.assertIsNone(question)
        self.assertIn("mileage", state["verified"])

    def test_no_cross_chat_state(self):
        first, _ = advance(initial_state(), "Бюджет 700.000")
        second = initial_state()
        self.assertEqual(first["pending_field"], "budget")
        self.assertIsNone(second["pending_field"])


if __name__ == "__main__":
    unittest.main()
