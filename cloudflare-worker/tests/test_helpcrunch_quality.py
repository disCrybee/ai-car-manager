import unittest
from pathlib import Path
from sys import path
path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from helpcrunch_quality import signals

class QualityTests(unittest.TestCase):
    def test_budget_refusal_does_not_repeat(self):
        x=signals("Не знаю, запропонуйте а я подумаю","Добре. Який максимальний пробіг?")
        self.assertEqual(x["budget_declined"],1)
        self.assertEqual(x["budget_repeated"],0)
        self.assertEqual(x["mileage_asked"],1)

    def test_unwanted_budget_repeat_detected(self):
        x=signals("Просто цікавить вартість","А який бюджет розглядаєте?")
        self.assertEqual(x["budget_repeated"],1)

    def test_no_customer_text_in_metrics(self):
        x=signals("Номер 0981234567, не знаю бюджет","Залиште номер телефону")
        self.assertNotIn("0981234567",str(x))
        self.assertEqual(set(x),{"budget_declined","budget_repeated","phone_requested","mileage_asked"})

if __name__=="__main__":
    unittest.main()
