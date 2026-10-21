import unittest
from pathlib import Path
from sys import path

path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpcrunch_api import test_message_payload


class HelpCrunchApiTests(unittest.TestCase):
    def test_disabled_by_default(self):
        with self.assertRaises(PermissionError):
            test_message_payload(123, 456, "Test", allowed_chat_id=123, allowed_agent_id=456)

    def test_only_exact_approved_manager_and_chat(self):
        for chat, agent in ((999, 456), (123, 999)):
            with self.assertRaises(PermissionError):
                test_message_payload(chat, agent, "Test", allowed_chat_id=123,
                                     allowed_agent_id=456, enabled=True)

    def test_valid_test_payload(self):
        data = test_message_payload(123, 456, " Test ",
                                    allowed_chat_id=123, allowed_agent_id=456,
                                    enabled=True)
        self.assertEqual(data, {"chat": 123, "agent": 456,
                                "text": "Test", "type": "message"})

    def test_empty_message_rejected(self):
        with self.assertRaises(ValueError):
            test_message_payload(123, 456, "  ", allowed_chat_id=123,
                                 allowed_agent_id=456, enabled=True)


if __name__ == "__main__":
    unittest.main()
