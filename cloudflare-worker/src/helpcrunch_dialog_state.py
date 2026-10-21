"""Pure qualification state transitions for HelpCrunch chats.

No automatic replies or external side effects. Persist returned state by chat ID.
"""
from helpcrunch_qualification_flow import next_clarification

def initial_state():
    return {"pending_field": None, "pending_text": None, "verified": {}}

def advance(state: dict, text: str) -> tuple[dict, str | None]:
    state = dict(state or initial_state())
    state["verified"] = dict(state.get("verified") or {})
    pending = state.get("pending_field")
    raw = (text or "").strip()
    if not raw:
        return state, None

    if pending:
        result = next_clarification(raw, pending)
        if result["pending_field"]:
            return state, result["question"]
        # A one-word answer must be retained with original figure.
        original = state.get("pending_text") or ""
        state["verified"][pending] = (original + " " + raw).strip()
        state["pending_field"] = None
        state["pending_text"] = None
        return state, None

    result = next_clarification(raw)
    if result["pending_field"]:
        state["pending_field"] = result["pending_field"]
        state["pending_text"] = raw
        return state, result["question"]
    return state, None
