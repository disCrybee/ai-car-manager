import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from sys import path
path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpcrunch_night_gate import eligible_night_event

K = ZoneInfo("Europe/Kyiv")
class NightGateTests(unittest.TestCase):
    def setUp(self):
        self.event = {"event":"message.chat.customer","chat_id":999,
                      "message_id":888,"application_id":777}
    def test_exact_schedule_and_opt_in(self):
        for hour, want in [(22,False),(23,True),(0,True),(7,True),(8,False),(14,False)]:
            now=datetime(2026,10,26,hour,0,tzinfo=K)
            self.assertEqual(eligible_night_event(self.event,"true",now=now),want)
            self.assertFalse(eligible_night_event(self.event,"false",now=now))
    def test_non_customer_event_and_bad_ids(self):
        now=datetime(2026,10,26,23,0,tzinfo=K)
        for k,v in (("event","message.chat.agent"),("chat_id",0),("message_id",None),("application_id","no")):
            data=dict(self.event)
            data[k]=v
            self.assertFalse(eligible_night_event(data,"true",now=now))
if __name__=="__main__":
    unittest.main()
