import unittest
from pathlib import Path
from sys import path
path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpcrunch_api import manager_candidates, test_message_payload

class AgentDiscoveryTests(unittest.TestCase):
    def test_only_manager_name_and_id_returned(self):
        response = {"data": [
            {"id": 17, "name": "Андрій", "email": "private@example.test"},
            {"id": 18, "name": "Олександр", "email": "another@example.test"},
        ]}
        self.assertEqual(manager_candidates(response), [{"id": 17, "name": "Андрій"}])

    def test_no_outbound_without_explicit_enabled_flag(self):
        with self.assertRaises(PermissionError):
            test_message_payload(123, 17, "Тест", allowed_chat_id=123, allowed_agent_id=17)

    def test_no_other_chat_even_if_enabled(self):
        with self.assertRaises(PermissionError):
            test_message_payload(123, 17, "Тест", allowed_chat_id=456, allowed_agent_id=17, enabled=True)

if __name__ == "__main__":
    unittest.main()
