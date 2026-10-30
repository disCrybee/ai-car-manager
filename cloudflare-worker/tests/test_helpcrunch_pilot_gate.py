import unittest
from pathlib import Path
from sys import path
path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpcrunch_test_dispatch import enabled_for_event, TEST_CHAT_ID

class PilotGateTests(unittest.TestCase):
    def setUp(self):
        self.event = {"event":"message.chat.customer","chat_id":TEST_CHAT_ID,
                      "message_id":123,"application_id":456}
    def test_default_off(self):
        for flag in ("", "false", "TRUE", "1", None):
            self.assertFalse(enabled_for_event(self.event, flag))
    def test_only_exact_chat_and_customer_event(self):
        self.assertTrue(enabled_for_event(self.event, "true"))
        for field,value in (("chat_id",60355),("message_id",0),
                            ("application_id",0),("event","message.chat.agent")):
            other = dict(self.event)
            other[field] = value
            self.assertFalse(enabled_for_event(other, "true"))
    def test_invalid_identifiers_fail_closed(self):
        other = dict(self.event)
        other["chat_id"] = "malformed"
        self.assertFalse(enabled_for_event(other, "true"))

if __name__ == "__main__":
    unittest.main()
