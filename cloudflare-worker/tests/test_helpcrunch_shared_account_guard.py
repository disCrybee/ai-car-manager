import unittest
from pathlib import Path
from sys import path
path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from helpcrunch_shared_account_guard import human_takeover_since

class SharedAgentTests(unittest.TestCase):
    def test_same_agent_manual_message_is_takeover(self):
        result={"data":[{"id":101,"from":"agent","type":"message","createdAt":"1793100000","agent":{"id":21}},
                        {"id":102,"from":"customer","type":"message","createdAt":"1793100001"}]}
        self.assertTrue(human_takeover_since(result,{201},since_timestamp=1793090000))
    def test_known_ai_messages_are_safe(self):
        result={"data":[{"id":201,"from":"agent","type":"message","createdAt":"1793100000","agent":{"id":21}},
                        {"id":102,"from":"customer","type":"message","createdAt":"1793100001"}]}
        self.assertFalse(human_takeover_since(result,{201},since_timestamp=1793090000))
    def test_past_messages_do_not_block(self):
        result={"data":[{"id":101,"from":"agent","type":"message","createdAt":"1793080000"}]}
        self.assertFalse(human_takeover_since(result,set(),since_timestamp=1793090000))
    def test_unknown_fails_closed(self):
        for data in ({},{ "data":[]},{"data":[{"from":"agent"}]}):
            self.assertTrue(human_takeover_since(data,set(),since_timestamp=1793090000))
    def test_private_note_blocks_automation(self):
        result={"data":[{"id":104,"from":"agent","type":"private","createdAt":"1793100000"}]}
        self.assertTrue(human_takeover_since(result,set(),since_timestamp=1793090000))

if __name__=="__main__":unittest.main()
