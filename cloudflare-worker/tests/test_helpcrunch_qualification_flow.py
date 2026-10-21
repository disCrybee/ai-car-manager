import unittest
from pathlib import Path
from sys import path

path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpcrunch_qualification_flow import next_clarification


class QualificationFlowTests(unittest.TestCase):
    def test_budget_requires_currency(self):
        result = next_clarification("Мій бюджет 700.000")
        self.assertEqual(result["pending_field"], "budget")
        self.assertIn("валют", result["question"].lower())
        self.assertEqual(next_clarification("у гривнях", "budget")["pending_field"], "budget")
        self.assertIsNone(next_clarification("грн", "budget")["pending_field"])

    def test_mileage_requires_units_and_scale(self):
        result = next_clarification("Пробіг до 100")
        self.assertEqual(result["pending_field"], "mileage")
        self.assertIsNotNone(result["question"])
        self.assertEqual(next_clarification("км", "mileage")["pending_field"], "mileage")
        self.assertIsNone(next_clarification("100 тисяч км", "mileage")["pending_field"])

    def test_explicit_units_need_no_clarification(self):
        self.assertIsNone(next_clarification("Бюджет 700000 грн")["question"])
        self.assertIsNone(next_clarification("Пробіг 100 тисяч миль")["question"])

    def test_no_unrelated_guess(self):
        self.assertIsNone(next_clarification("Хочу BMW X5")["question"])


if __name__ == "__main__":
    unittest.main()
