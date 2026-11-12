import unittest
from pathlib import Path
from sys import path
path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpcrunch_api import test_message_payload

class RestrictedAiSendTests(unittest.TestCase):
    def test_exact_chat_and_agent_only(self):
        payload = test_message_payload(
            60354, 21, "Тест", allowed_chat_id=60354,
            allowed_agent_id=21, enabled=True,
        )
        self.assertEqual(payload["chat"], 60354)
        self.assertEqual(payload["agent"], 21)
        for chat, agent in ((60355, 21), (60354, 22)):
            with self.assertRaises(PermissionError):
                test_message_payload(chat, agent, "Тест",
                    allowed_chat_id=60354, allowed_agent_id=21, enabled=True)

if __name__ == "__main__":
    unittest.main()
