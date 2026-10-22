import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from sys import path
path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpcrunch_planner import plan_incoming

NIGHT = datetime(2026, 10, 23, 1, 0, tzinfo=ZoneInfo("Europe/Kyiv"))
DAY = datetime(2026, 10, 23, 12, 0, tzinfo=ZoneInfo("Europe/Kyiv"))


def event(text, event_type="message.chat.customer"):
    return json.dumps({
        "event": event_type,
        "eventData": {"chat_id": 60311, "message": {
            "id": 101, "applicationId": 9, "text": text
        }}
    }).encode()


class PlannerTests(unittest.TestCase):
    def test_night_budget_clarification_dry_run(self):
        result = plan_incoming(event("Бюджет 700.000"), now=NIGHT)
        self.assertTrue(result["accepted"])
        self.assertIn("гривнях", result["suggested_reply"].lower())
        self.assertEqual(result["state"]["pending_field"], "budget")

    def test_followup_uses_existing_state(self):
        prior = plan_incoming(event("Бюджет 700.000"), now=NIGHT)["state"]
        result = plan_incoming(event("грн"), state=prior, now=NIGHT)
        self.assertIsNone(result["suggested_reply"])
        self.assertIn("700.000", result["state"]["verified"]["budget"])

    def test_no_daytime_processing(self):
        result = plan_incoming(event("Бюджет 700.000"), now=DAY)
        self.assertFalse(result["accepted"])
        self.assertIsNone(result["suggested_reply"])

    def test_no_agent_event_processing(self):
        result = plan_incoming(event("Бюджет 700.000", "message.chat.agent"), now=NIGHT)
        self.assertFalse(result["accepted"])


if __name__ == "__main__":
    unittest.main()
