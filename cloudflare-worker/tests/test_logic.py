import os
import sys
import unittest

HERE = os.path.dirname(__file__)
SRC = os.path.abspath(os.path.join(HERE, "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from utils import is_affirmative, is_negative
from name_catalog import CATALOG, resolve_brand, resolve_model
from vehicle_logic import (
    explicit_selection_intent,
    extract_deterministic,
    new_memory,
    next_question,
    qualification_ready,
    is_question,
)


class DialogLogicTests(unittest.TestCase):
    def test_audi_ukrainian_brand_and_model(self):
        memory, _ = extract_deterministic(new_memory(), "Ауді A4")
        self.assertEqual(memory["brand"], "Audi")
        self.assertEqual(memory["model"], "A4")
        topic, _ = next_question(memory)
        self.assertEqual(topic, "year")

    def test_global_catalog_and_fuzzy_names(self):
        self.assertGreaterEqual(sum(len(models) for models in CATALOG.values()), 400)
        cases = (
            ("тойота секвоя", "Toyota", "Sequoia"),
            ("тайота секвойя", "Toyota", "Sequoia"),
            ("Toyota Camry", "Toyota", "Camry"),
            ("Фольксваген Тігуан", "Volkswagen", "Tiguan"),
            ("Хюндай Туксон", "Hyundai", "Tucson"),
            ("Кіа Спортейдж", "Kia", "Sportage"),
            ("Мерседес GLE", "Mercedes-Benz", "GLE"),
            ("BMW X5", "BMW", "X5"),
            ("Tesla Model Y", "Tesla", "Model Y"),
            ("Nissan Rogue", "Nissan", "Rogue"),
            ("Ford F-150", "Ford", "F-150"),
            ("BYD Seal", "BYD", "Seal"),
            ("Geely Monjaro", "Geely", "Monjaro"),
            ("Skoda Octavia", "Skoda", "Octavia"),
            ("Porsche Macan", "Porsche", "Macan"),
        )
        for value, brand, model in cases:
            with self.subTest(value=value):
                self.assertEqual(resolve_brand(value), brand)
                self.assertEqual(resolve_model(brand, value), model)

    def test_no_unrelated_car_guess(self):
        self.assertIsNone(resolve_model("Toyota", "абракадабра"))
        self.assertIsNone(resolve_brand("добрий день"))

    def test_vehicle_name_normalization(self):
        cases = (
            ("тойота секвоя", "Toyota", "Sequoia"),
            ("тойота секвойя", "Toyota", "Sequoia"),
            ("тойота сиквоя", "Toyota", "Sequoia"),
            ("toyta sequoya", "Toyota", "Sequoia"),
            ("Toyota Sequoia", "Toyota", "Sequoia"),
            ("рендж ровер евок", "Range Rover", "Evoque"),
            ("форд едж", "Ford", "Edge"),
            ("кіа спортейдж", "Kia", "Sportage"),
            ("субару форестер", "Subaru", "Forester"),
        )
        for raw, brand, model in cases:
            with self.subTest(raw=raw):
                memory, _ = extract_deterministic(new_memory(), raw)
                self.assertEqual(memory["brand"], brand)
                self.assertEqual(memory["model"], model)
                self.assertEqual(next_question(memory)[0], "year")

    def test_range_rover_is_not_a_question(self):
        self.assertFalse(is_question("Range Rover Evoque"))
        self.assertFalse(is_question("Range Rover Sport"))
        self.assertTrue(is_question("Який запас ходу у Range Rover?"))
        memory, _ = extract_deterministic(new_memory(), "Range Rover Evoque")
        self.assertEqual(memory["brand"], "Range Rover")
        self.assertEqual(memory["model"], "Evoque")
        topic, _ = next_question(memory)
        self.assertEqual(topic, "year")

    def test_ambiguous_mileage_requires_clarification(self):
        memory = new_memory()
        memory.update({"brand": "Toyota", "model": "Sequoia", "year": "2018", "last_question_topic": "mileage"})
        memory, _ = extract_deterministic(memory, "до 100")
        self.assertIsNone(memory["mileage"])
        self.assertEqual(memory["mileage_pending"], "до 100")
        topic, question = next_question(memory)
        self.assertEqual(topic, "mileage")
        self.assertIn("до 100", question)
        memory, _ = extract_deterministic(memory, "100 тисяч км")
        self.assertEqual(memory["mileage"], "до 100000 км")
        self.assertIsNone(memory["mileage_pending"])
        self.assertEqual(next_question(memory)[0], "trim")

    def test_mercedes_e_class(self):
        memory, _ = extract_deterministic(new_memory(), "Mercedes Benz E-class")
        self.assertEqual(memory["brand"], "Mercedes-Benz")
        self.assertEqual(memory["model"], "E-class")

    def test_cadillac_reference_flow(self):
        memory, _ = extract_deterministic(new_memory(), "Cadillac Escalade")
        self.assertEqual(memory["brand"], "Cadillac")
        self.assertEqual(memory["model"], "Escalade")

        memory["last_question_topic"] = "year"
        memory, _ = extract_deterministic(memory, "2012")
        self.assertEqual(memory["year"], "2012")

        memory["last_question_topic"] = "mileage"
        memory, _ = extract_deterministic(memory, "до 200.000 км")
        self.assertIn("200000", memory["mileage"])

        memory["last_question_topic"] = "trim"
        memory, _ = extract_deterministic(memory, "Максимальна")
        self.assertEqual(memory["trim"], "Максимальна")
        self.assertTrue(qualification_ready(memory))

    def test_year_range_is_not_model(self):
        memory, _ = extract_deterministic(new_memory(), "Audi A4")
        memory["last_question_topic"] = "year"
        memory, _ = extract_deterministic(memory, "2015-2017")
        self.assertEqual(memory["model"], "A4")
        self.assertEqual(memory["year"], "2015-2017")

    def test_yes_no(self):
        self.assertTrue(is_affirmative("Так, давайте"))
        self.assertTrue(is_affirmative("Да"))
        self.assertTrue(is_negative("Ні, дякую"))
        self.assertTrue(is_negative("Нет"))

    def test_explicit_order_intent(self):
        self.assertTrue(explicit_selection_intent("Хочу замовити авто"))
        self.assertTrue(explicit_selection_intent("Пригін під ключ"))
        self.assertFalse(explicit_selection_intent("Яка вартість під ключ?"))


if __name__ == "__main__":
    unittest.main()
