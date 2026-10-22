import unittest
from pathlib import Path
from sys import path

path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpcrunch_qualify import qualification_question


class QualifyTests(unittest.TestCase):
    def test_ambiguous_budget(self):
        self.assertIn("гривнях", qualification_question("Бюджет 700.000", field="budget"))
        self.assertIn("доларах", qualification_question("Бюджет 30 тисяч", field="budget") or "")
        self.assertIsNone(qualification_question("Бюджет 30 тисяч грн", field="budget"))
        self.assertIsNone(qualification_question("Бюджет 700000 доларів", field="budget"))

    def test_explicit_budget(self):
        self.assertIsNone(qualification_question("Бюджет 700000 грн", field="budget"))
        self.assertIsNone(qualification_question("Бюджет $25000", field="budget"))

    def test_ambiguous_mileage(self):
        self.assertIn("100 тисяч", qualification_question("Пробіг до 100", field="mileage"))
        self.assertIn("милі", qualification_question("Пробіг до 100 тисяч", field="mileage"))

    def test_explicit_mileage(self):
        self.assertIsNone(qualification_question("Пробіг до 100000 км", field="mileage"))
        self.assertIsNone(qualification_question("Пробіг до 60000 миль", field="mileage"))


if __name__ == "__main__":
    unittest.main()
