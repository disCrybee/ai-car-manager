import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from sys import path

path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpcrunch_preview_pipeline import process_preview
from helpcrunch_webhook import describe_event


def sample(text="Бюджет 700.000", message_id=101):
    raw = json.dumps({"event": "message.chat.customer", "eventData": {
        "chat_id": 60311, "message": {"id": message_id, "applicationId": 9, "text": text}
    }}).encode()
    now = datetime(2026, 10, 23, 1, tzinfo=ZoneInfo("Europe/Kyiv"))
    return raw, describe_event(raw, now=now)


class TestPreview(unittest.IsolatedAsyncioTestCase):
    async def test_no_database_preview_has_no_side_effect(self):
        raw, meta = sample()
        result = await process_preview(raw, meta)
        self.assertEqual(result["status"], "preview")
        self.assertTrue(result["clarification_needed"])

    async def test_daytime_event_ignored(self):
        raw, meta = sample()
        meta["would_process"] = False
        self.assertEqual((await process_preview(raw, meta))["status"], "ignored")


if __name__ == "__main__":
    unittest.main()
