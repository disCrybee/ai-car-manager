import unittest
from pathlib import Path
from sys import path
path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpcrunch_shipping_lookup import shipping_context, confirmed_route_reply
from helpcrunch_groq import build_messages

class ShippingContextTests(unittest.TestCase):
    def test_no_claim_without_exact_auction_location(self):
        question = [{"role":"user","content":"Скільки доставка Tesla зі США?"}]
        value = shipping_context(question)
        self.assertIn("точну локацію", value)
        self.assertNotIn("$", value)
    def test_known_route_from_price_sheet(self):
        question = [{"role":"user","content":"Яка доставка Copart ABILENE - Texas?"}]
        value = shipping_context(question)
        self.assertIn("Houston", value)
        self.assertIn("500", value)
        self.assertIn("не повна вартість", value)
        prompt = build_messages("Auction Auto", question, company_context=value)[0]["content"]
        self.assertIn("ABILENE", prompt)
    def test_deterministic_exact_tariff_reply(self):
        turns = [{"role":"user","content":"Скільки коштує доставка автомобіля з Copart Abilene, Texas?"}]
        reply = confirmed_route_reply(turns)
        self.assertIsNotNone(reply)
        self.assertIn("$500", reply)
        self.assertIn("Houston", reply)
        self.assertIn("Клайпеди", reply)
        self.assertIn("$1350", reply)
        self.assertIn("$1650", reply)
        self.assertIn("$1850", reply)
        self.assertIn("$2150", reply)
    def test_passenger_quote_short_and_complete(self):
        turns = [{"role": "user", "content":
                  "Скільки буде коштувати доставка легкового авто з Copart Abilene, Texas до Клайпеди?"}]
        reply = confirmed_route_reply(turns)
        self.assertIn("$500", reply)
        self.assertIn("$1350", reply)
        self.assertIn("$1850", reply)
        self.assertNotIn("$1650", reply)
        self.assertNotIn("який спосіб транспортування", reply)
        self.assertIn("Комплекс послуг", reply)
        self.assertNotIn("актуальність тарифу", reply)

    def test_suv_followup_uses_existing_route(self):
        turns = [
            {"role":"user","content":"Скільки коштує доставка легкового авто з Copart Abilene, Texas до Клайпеди?"},
            {"role":"assistant","content":"Суша $500, море $1350"},
            {"role":"user","content":"Окей, дякую. А якщо це буде кросовер?"},
        ]
        reply = confirmed_route_reply(turns)
        self.assertIsNotNone(reply)
        self.assertIn("$500", reply)
        self.assertIn("$1650", reply)
        self.assertIn("$2150", reply)
        self.assertNotIn("$1400", reply)
        self.assertNotIn("$1600", reply)
    def test_no_deterministic_quote_without_location(self):
        turns = [{"role":"user","content":"Скільки коштує доставка з Texas?"}]
        self.assertIsNone(confirmed_route_reply(turns))
    def test_just_state_does_not_leak_price(self):
        question = [{"role":"user","content":"Доставка Copart Texas скільки?"}]
        self.assertNotIn("$", shipping_context(question))
    def test_other_topics_do_not_inject_pricing(self):
        question = [{"role":"user","content":"Шукаю BMW X5"}]
        self.assertEqual(shipping_context(question), "")

if __name__ == "__main__":
    unittest.main()
