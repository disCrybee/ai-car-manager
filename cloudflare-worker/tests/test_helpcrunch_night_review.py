import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from sys import path
path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from helpcrunch_night_review import evaluate_night_chat

class Query:
    def bind(self,*args):return self
    async def first(self):return None
class DB:
    def prepare(self,sql):return Query()

class NightReviewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.metadata={"event":"message.chat.customer","chat_id":101,"message_id":44,"application_id":7}
        self.night=datetime(2026,10,26,23,15,tzinfo=ZoneInfo("Europe/Kyiv"))
        self.messages={"data":[{"id":44,"from":"customer","createdAt":1793050000,"type":"message"}]}
    async def test_night_read_only_ready(self):
        result=await evaluate_night_chat(self.metadata,"true","Auction Auto",DB(),self.messages,shift_started=1793040000,now=self.night)
        self.assertEqual(result["reason"],"read-only-ready")
        self.assertEqual(result["history_turns"],0)
    async def test_manual_operator_blocks(self):
        incoming={"data":[{"id":555,"from":"agent","type":"message","createdAt":1793050000}]}
        result=await evaluate_night_chat(self.metadata,"true","Auction Auto",DB(),incoming,shift_started=1793040000,now=self.night)
        self.assertFalse(result["eligible"])
    async def test_unknown_brand_and_missing_state_fail(self):
        self.assertTrue((await evaluate_night_chat(self.metadata,"true",None,DB(),self.messages,shift_started=1793040000,now=self.night))["eligible"])
        self.assertFalse((await evaluate_night_chat(self.metadata,"true","Auction Auto",None,self.messages,shift_started=1793040000,now=self.night))["eligible"])
if __name__=="__main__":unittest.main()
