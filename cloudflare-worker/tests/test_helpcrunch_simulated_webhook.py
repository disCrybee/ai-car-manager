"""End-to-end simulated HelpCrunch webhook -> planner -> D1 storage tests.

Uses an in-memory D1 stand-in. No customer messages, Cloudflare API, or secrets.
"""
import json
import unittest
from datetime import datetime
from pathlib import Path
from sys import path
from zoneinfo import ZoneInfo

path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpcrunch_preview_pipeline import process_preview
from helpcrunch_webhook import describe_event


NIGHT = datetime(2026, 10, 27, 0, 30, tzinfo=ZoneInfo("Europe/Kyiv"))
DAY = datetime(2026, 10, 27, 14, 0, tzinfo=ZoneInfo("Europe/Kyiv"))


class Statement:
    def __init__(self, db, sql):
        self.db, self.sql, self.args = db, sql, ()
    def bind(self, *args):
        self.args = args
        return self
    async def first(self):
        if "hc_dialog_state" in self.sql:
            state = self.db.states.get(self.args)
            return {"state_json": state} if state else None
        return {"event_key": self.args[0]} if self.args[0] in self.db.events else None


class FakeD1:
    def __init__(self):
        self.states = {}
        self.events = set()
    def prepare(self, sql):
        return Statement(self, sql)
    async def batch(self, statements):
        event, chat, app = statements[0].args
        if event in self.events:
            raise RuntimeError("duplicate event")
        self.events.add(event)
        self.states[(chat, app)] = statements[1].args[2]


def make_event(text, message_id, chat=100, application=9, now=NIGHT):
    raw = json.dumps({
        "event": "message.chat.customer",
        "eventData": {"chat_id": chat, "message": {
            "id": message_id, "applicationId": application, "text": text,
        }},
    }, ensure_ascii=False).encode()
    return raw, describe_event(raw, now=now)


class SimulatedWebhookTests(unittest.IsolatedAsyncioTestCase):
    async def test_budget_followup_is_persisted(self):
        db = FakeD1()
        raw, meta = make_event("Бюджет 700.000", 101)
        first = await process_preview(raw, meta, db, now=NIGHT)
        self.assertEqual(first["status"], "stored")
        self.assertTrue(first["clarification_needed"])
        self.assertEqual(json.loads(db.states[(100, 9)])["pending_field"], "budget")
        raw, meta = make_event("у гривнях", 102)
        second = await process_preview(raw, meta, db, now=NIGHT)
        self.assertEqual(second["status"], "stored")
        state = json.loads(db.states[(100, 9)])
        self.assertIsNone(state["pending_field"])
        self.assertIn("700.000", state["verified"]["budget"])
        self.assertIn("гривнях", state["verified"]["budget"])

    async def test_same_message_does_not_advance_twice(self):
        db = FakeD1()
        raw, meta = make_event("Пробіг до 100", 201)
        self.assertEqual((await process_preview(raw, meta, db, now=NIGHT))["status"], "stored")
        self.assertEqual((await process_preview(raw, meta, db, now=NIGHT))["status"], "duplicate")
        self.assertEqual(len(db.events), 1)

    async def test_daytime_does_not_store(self):
        db = FakeD1()
        raw, meta = make_event("Бюджет 700.000", 301, now=DAY)
        self.assertEqual((await process_preview(raw, meta, db, now=DAY))["status"], "ignored")
        self.assertFalse(db.states)

    async def test_same_chat_id_different_site_is_isolated(self):
        db = FakeD1()
        raw, meta = make_event("Бюджет 700.000", 401, application=9)
        await process_preview(raw, meta, db, now=NIGHT)
        raw, meta = make_event("Пробіг до 100", 402, application=10)
        await process_preview(raw, meta, db, now=NIGHT)
        self.assertEqual(len(db.states), 2)


if __name__ == "__main__":
    unittest.main()
