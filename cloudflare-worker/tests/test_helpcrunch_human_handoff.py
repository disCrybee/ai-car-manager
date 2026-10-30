import unittest
from pathlib import Path
from sys import path
path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpcrunch_human_handoff import human_operator_present

class HumanHandoffTests(unittest.TestCase):
    def test_real_operator_blocks_night_auto_reply(self):
        self.assertTrue(human_operator_present({"data":[{"from":"agent","type":"message","agent":{"id":42}}]}))
    def test_bot_agent_only_does_not_block(self):
        self.assertFalse(human_operator_present({"data":[
            {"from":"customer","type":"message"},
            {"from":"agent","type":"message","agent":{"id":21}},
        ]}))
    def test_unknown_response_fails_closed(self):
        self.assertTrue(human_operator_present({"data":[{"from":"agent","type":"message"}]}))
        self.assertTrue(human_operator_present({}))
        self.assertTrue(human_operator_present({"data":[]}))
    def test_tech_status_is_not_a_manager_reply(self):
        self.assertFalse(human_operator_present({"data":[{"from":"agent","type":"tech"}]}))
if __name__=="__main__":
    unittest.main()
