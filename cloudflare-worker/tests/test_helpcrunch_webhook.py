import hashlib
import hmac
import json
import unittest
from datetime import datetime
from pathlib import Path
from sys import path
from zoneinfo import ZoneInfo

path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpcrunch_webhook import describe_event, is_night, verify_signature

KYIV = ZoneInfo("Europe/Kyiv")


def example_event(app=77, event="message.chat.customer", text="Привіт"):
    return json.dumps({
        "event": event,
        "id": "event-1",
        "eventData": {
            "chat_id": 5224081,
            "message": {"id": 38488, "applicationId": app, "text": text},
        },
    }, ensure_ascii=False).encode("utf-8")


class HelpCrunchWebhookTests(unittest.TestCase):
    def test_signature_verifies_raw_body(self):
        body = example_event()
        signature = hmac.new(b"secret", body, hashlib.sha1).hexdigest()
        self.assertTrue(verify_signature(body, "secret", signature))
        self.assertFalse(verify_signature(body + b" ", "secret", signature))
        self.assertFalse(verify_signature(body, "", signature))
        self.assertFalse(verify_signature(body, "secret", "bad"))

    def test_night_window_kyiv(self):
        self.assertTrue(is_night(datetime(2026, 10, 20, 23, 0, tzinfo=KYIV)))
        self.assertTrue(is_night(datetime(2026, 10, 21, 7, 59, tzinfo=KYIV)))
        self.assertFalse(is_night(datetime(2026, 10, 21, 8, 0, tzinfo=KYIV)))
        self.assertFalse(is_night(datetime(2026, 10, 20, 22, 59, tzinfo=KYIV)))

    def test_correct_site_and_event_required(self):
        night = datetime(2026, 10, 20, 23, 30, tzinfo=KYIV)
        self.assertTrue(describe_event(example_event(), 77, night)["would_process"])
        self.assertFalse(describe_event(example_event(app=78), 77, night)["would_process"])
        self.assertFalse(describe_event(example_event(event="message.chat.agent"), 77, night)["would_process"])
        self.assertFalse(describe_event(example_event(text=""), 77, night)["would_process"])
        self.assertTrue(describe_event(example_event(), None, night)["would_process"])
        self.assertTrue(describe_event(example_event(app=78), None, night)["would_process"])
        self.assertFalse(describe_event(example_event(app=None), None, night)["would_process"])

    def test_no_customer_text_in_metadata(self):
        result = describe_event(example_event(text="Sensitive customer message"), 77,
                                datetime(2026, 10, 20, 23, 0, tzinfo=KYIV))
        self.assertNotIn("Sensitive", str(result))


if __name__ == "__main__":
    unittest.main()
