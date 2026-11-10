import json
import unittest
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from sys import path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpcrunch_media import has_media, media_reply
from helpcrunch_webhook import describe_event
from helpcrunch_night_dispatch import process_night_event

K = ZoneInfo("Europe/Kyiv")
NOW = datetime(2026, 11, 10, 23, 14, tzinfo=K)


class MediaTests(unittest.TestCase):
    def test_formats_and_plain_text(self):
        for message in ({"attachments": [{"id": 44}]}, {"attachmentId": 44},
                        {"type": "image"}, {"text": '<img src="https://example.com/a">'},
                        {"text": "https://example.com/a.JPG?token=secret"}):
            self.assertTrue(has_media(message), message)
        for message in ({}, {"text": "Toyota Hilux"}, {"text": "380501234567"},
                        {"text": "https://example.com/car"}, {"attachments": []}):
            self.assertFalse(has_media(message), message)

    def test_metadata_does_not_expose_attachment(self):
        raw = json.dumps({"event": "message.chat.customer", "eventData": {
            "chat_id": 9191, "message": {"id": 51, "applicationId": 88,
            "attachments": [{"url": "https://example.com/private.jpg"}]}}}).encode()
        result = describe_event(raw, now=NOW)
        self.assertTrue(result["has_media"])
        self.assertNotIn("private", str(result))

    def test_calendar_day_and_existing_phone(self):
        self.assertIn("завтра", media_reply(NOW))
        self.assertIn("сьогодні", media_reply(NOW.replace(hour=1)))
        self.assertNotIn("Залиште", media_reply(NOW, phone_received=True))


class MediaDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def dispatch(self, *, incoming=None, media=True, completed=False,
                       live=True, eligible=True, latest=51, old=None):
        meta = {"event": "message.chat.customer", "chat_id": 9191,
                "application_id": 88, "message_id": 51, "has_media": media}
        env = SimpleNamespace(HELPCRUNCH_NIGHT_ENABLED="true",
                              HELPCRUNCH_NIGHT_SEND_ENABLED="true",
                              HELPCRUNCH_API_KEY="test", HC_DB=object())
        history = {"data": [{"id": 51, "from": "customer", "createdAt": NOW.timestamp()}]}
        with ExitStack() as stack:
            mocks = {}
            for name, value in {
                "evaluate_night_chat": {"eligible": eligible, "reason": "manual-takeover"},
                "claim_event": True, "get_night_completion": completed,
                "load_night_history": old or [], "generate_reply": "Unexpected AI reply",
                "get_chat_messages": {"data": [{"id": latest, "from": "customer"}]},
                "record_bot_message_id": None, "save_night_history": None,
                "set_night_completion": None, "record_quality": None,
            }.items():
                mocks[name] = stack.enter_context(patch(
                    "helpcrunch_night_dispatch." + name, new=AsyncMock(return_value=value)))
            request = stack.enter_context(patch("helpcrunch_night_dispatch._request",
                new=AsyncMock(side_effect=[{"id": 9191}, {"id": 99, "chat": 9191}])))
            stack.enter_context(patch("helpcrunch_night_dispatch.is_night", return_value=True))
            result = await process_night_event(meta, incoming, env=env, brand=None,
                now=NOW, live=live, history_response=history)
        return result, mocks, request

    async def test_attachment_without_caption_or_ai_key(self):
        result, mocks, request = await self.dispatch()
        self.assertEqual(result["mode"], "night-replied")
        self.assertIn("Залиште", request.call_args.args[3]["text"])
        mocks["generate_reply"].assert_not_awaited()
        mocks["set_night_completion"].assert_not_awaited()

    async def test_existing_phone_not_requested_again(self):
        for kwargs in ({"completed": True}, {"old": [{"role": "user", "content": "+380501234567"}]}):
            result, mocks, request = await self.dispatch(**kwargs)
            self.assertEqual(result["mode"], "night-replied")
            self.assertNotIn("Залиште", request.call_args.args[3]["text"])

    async def test_safety_gates_still_prevent_sends(self):
        for kwargs, mode in (({"live": False}, "night-shadow-ready"),
                             ({"eligible": False}, "night-blocked"),
                             ({"latest": 52}, "night-stale-message")):
            result, mocks, request = await self.dispatch(**kwargs)
            self.assertEqual(result["mode"], mode)
            request.assert_not_awaited()

    async def test_empty_non_media_stays_invalid(self):
        result, _, request = await self.dispatch(media=False)
        self.assertEqual(result["mode"], "night-invalid-content")
        request.assert_not_awaited()

    async def test_numeric_media_url_is_not_a_phone(self):
        result, mocks, _ = await self.dispatch(incoming="https://example.com/0501234567.jpg")
        self.assertEqual(result["mode"], "night-replied")
        mocks["set_night_completion"].assert_not_awaited()
