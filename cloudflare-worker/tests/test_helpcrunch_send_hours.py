import unittest
from datetime import datetime, timezone
from pathlib import Path
from sys import path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpcrunch_webhook import is_night
from helpcrunch_test_dispatch import enabled_for_event, TEST_CHAT_ID
from helpcrunch_api import _request, send_test_message

KYIV = ZoneInfo("Europe/Kyiv")


class ScheduleTests(unittest.TestCase):
    def test_every_minute_including_dst_days(self):
        event = {"event": "message.chat.customer", "chat_id": TEST_CHAT_ID,
                 "message_id": 1, "application_id": 1}
        for month, day in ((1, 15), (7, 15), (3, 29), (10, 25)):
            for minute in range(24 * 60):
                local = datetime(2026, month, day, minute // 60, minute % 60, tzinfo=KYIV)
                expected = minute >= 23 * 60 or minute < 8 * 60
                self.assertEqual(is_night(local.astimezone(timezone.utc)), expected)
                self.assertEqual(enabled_for_event(event, "true", now=local), expected)

    def test_exact_seconds(self):
        for hour, minute, second, expected in ((22, 59, 59, False), (23, 0, 0, True),
                                               (7, 59, 59, True), (8, 0, 0, False)):
            self.assertEqual(is_night(datetime(2026, 11, 10, hour, minute, second,
                                              tzinfo=KYIV)), expected)


class SendBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fetch = AsyncMock(return_value=SimpleNamespace(
            status=200, text=AsyncMock(return_value='{"id":99}')))
        workers = patch.dict("sys.modules", {"workers": SimpleNamespace(fetch=self.fetch)})
        workers.start()
        self.addCleanup(workers.stop)

    async def test_all_outbound_paths_blocked_in_daytime(self):
        with patch("helpcrunch_api.is_night", return_value=False):
            with self.assertRaises(PermissionError):
                await _request("key", "POST", "/messages", {"text": "night reply"})
            with self.assertRaises(PermissionError):
                await send_test_message("key", 1, 2, "pilot/manual reply",
                    allowed_chat_id=1, allowed_agent_id=2, enabled=True)
        self.fetch.assert_not_awaited()

    async def test_night_send_and_daytime_reads(self):
        with patch("helpcrunch_api.is_night", return_value=True):
            self.assertEqual(await _request("key", "POST", "/messages", {}), {"id": 99})
        with patch("helpcrunch_api.is_night", return_value=False):
            await _request("key", "GET", "/chats/1/messages")
        self.assertEqual(self.fetch.await_count, 2)

    async def test_cutoff_rechecked_for_each_send(self):
        # A reply ready at 07:59:59 may send; the next at 08:00 may not.
        with patch("helpcrunch_api.is_night", side_effect=[True, False]):
            await _request("key", "POST", "/messages", {})
            with self.assertRaises(PermissionError):
                await _request("key", "POST", "/messages", {})
        self.fetch.assert_awaited_once()
