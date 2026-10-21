import unittest
from pathlib import Path
from sys import path

path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpcrunch_conversation import helpcrunch_system_prompt


class HelpCrunchConversationTests(unittest.TestCase):
    def test_junior_manager_role_and_politeness(self):
        prompt = helpcrunch_system_prompt("Auction Auto")
        self.assertIn("молодшого менеджера", prompt)
        self.assertIn("Звертайся на «Ви»", prompt)
        self.assertIn("старшому менеджеру", prompt)
        self.assertIn("Auction Auto", prompt)
        self.assertNotIn("Ти — AI-консультант", prompt)

    def test_do_not_claim_unconfirmed_handoff(self):
        prompt = helpcrunch_system_prompt("Atlantic Express")
        self.assertIn("тільки після успішного підтвердження CRM", prompt)
        self.assertIn("що це автоматизована консультація", prompt)
        self.assertIn("Atlantic Express", prompt)


if __name__ == "__main__":
    unittest.main()
