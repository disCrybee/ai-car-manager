"""Pure HelpCrunch event processing planner.

The planner cannot send messages, access credentials, or write the database.
Caller must explicitly implement persistence/dispatch after separate testing.
"""
import json
from helpcrunch_webhook import describe_event
from helpcrunch_dialog_state import advance, initial_state


def plan_incoming(raw_body: bytes, state: dict | None = None, now=None) -> dict:
    metadata = describe_event(raw_body, now=now)
    if not metadata["would_process"]:
        return {"accepted": False, "reason": "not_eligible", "state": state,
                "suggested_reply": None, "metadata": metadata}

    payload = json.loads(raw_body)
    data = payload["eventData"]
    message = data.get("message") or {}
    next_state, clarification = advance(state or initial_state(), message["text"])
    return {"accepted": True, "reason": "planned_only", "state": next_state,
            "suggested_reply": clarification, "metadata": metadata}
