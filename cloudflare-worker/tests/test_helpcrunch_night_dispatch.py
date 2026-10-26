import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from sys import path
from types import SimpleNamespace
path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from helpcrunch_night_dispatch import shift_start_timestamp, extract_created_id, process_night_event, incoming_is_latest_customer_message, confirmed_chat_id, receipt_matches_chat

K=ZoneInfo("Europe/Kyiv")
class NightDispatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.meta={"event":"message.chat.customer","chat_id":9191,"message_id":51,"application_id":88}
        self.env=SimpleNamespace(HELPCRUNCH_NIGHT_ENABLED="false")
    def test_start_for_both_sides_of_midnight(self):
        for hour in (23,0,7):
            current=datetime(2026,10,26,hour,tzinfo=K)
            stamp=shift_start_timestamp(current)
            expected=datetime(2026,10,26 if hour==23 else 25,23,tzinfo=K)
            self.assertEqual(stamp,int(expected.timestamp()))
    def test_stale_customer_message_prevents_reply(self):
        history = {"data": [
            {"id": 52, "from": "customer"},
            {"id": 51, "from": "customer"},
        ]}
        self.assertFalse(incoming_is_latest_customer_message(history, 51))
        self.assertTrue(incoming_is_latest_customer_message(history, 52))
        self.assertFalse(incoming_is_latest_customer_message({}, 52))

    def test_id_receipt_must_be_confirmed(self):
        self.assertEqual(extract_created_id({"id":55}),55)
        self.assertEqual(extract_created_id({"data":{"id":55}}),55)
        for body in ({},{ "id":None},{"id":"55"}):
            with self.assertRaises(ValueError):extract_created_id(body)
    def test_chat_preflight_requires_exact_identity(self):
        self.assertTrue(confirmed_chat_id({"id":60360},60360))
        self.assertTrue(confirmed_chat_id({"data":{"id":60360}},60360))
        self.assertFalse(confirmed_chat_id({"id":60359},60360))
        self.assertFalse(confirmed_chat_id({},60360))
        self.assertFalse(confirmed_chat_id({"data":[]},60360))

    def test_receipt_target_must_match_chat(self):
        self.assertEqual(receipt_matches_chat({"id":70,"chat":60360},60360),70)
        self.assertEqual(receipt_matches_chat({"data":{"id":70,"chat":{"id":60360}}},60360),70)
        self.assertEqual(receipt_matches_chat({"id":70},60360),70)
        with self.assertRaises(ValueError):
            receipt_matches_chat({"id":70,"chat":60359},60360)

    async def test_no_send_when_disabled(self):
        result=await process_night_event(self.meta,"Скільки доставка?",env=self.env,
            brand="Auction Auto",now=datetime(2026,10,26,23,tzinfo=K),live=True)
        self.assertEqual(result["mode"],"night-off")
    async def test_no_send_without_known_brand(self):
        self.env.HELPCRUNCH_NIGHT_ENABLED="true"
        result=await process_night_event(self.meta,"Доброго вечора",env=self.env,
            brand=None,now=datetime(2026,10,26,23,tzinfo=K),live=True)
        self.assertEqual(result["mode"],"night-not-configured")

if __name__=="__main__":unittest.main()
