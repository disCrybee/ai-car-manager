"""Pure HelpCrunch qualification transitions; no network or outgoing replies."""
import re
from helpcrunch_qualification_flow import next_clarification, CURRENCY, MILEAGE_UNIT, THOUSANDS

NUMBER = re.compile(r"(?<!\w)\d[\d\s.,]*(?!\w)")


def initial_state():
    return {"pending_field": None, "pending_text": None, "verified": {}}


def advance(state: dict, text: str) -> tuple[dict, str | None]:
    """Preserve unconfirmed quantities, and resolve only when units and scale are known."""
    state = dict(state or initial_state())
    state["verified"] = dict(state.get("verified") or {})
    pending = state.get("pending_field")
    raw = (text or "").strip()
    if not raw:
        return state, None

    if pending:
        original = state.get("pending_text") or ""
        combined = (original + " " + raw).strip()
        if pending == "budget":
            confirmed = bool(CURRENCY.search(raw))
            question = "Уточніть, будь ласка, валюту бюджету: гривні, долари США чи євро?"
        else:
            has_unit = bool(MILEAGE_UNIT.search(combined))
            has_number = bool(NUMBER.search(combined))
            # '100' by itself has unknown scale even after 'км'; do not guess 100,000.
            has_scale = bool(THOUSANDS.search(combined)) or bool(re.search(
                r"(?<!\d)\d{4,}(?!\d)|\d{1,3}[.,\s]\d{3}(?!\d)", combined
            ))
            confirmed = has_unit and has_number and has_scale
            question = ("Уточніть, будь ласка: пробіг до 100 чи до 100 тисяч? "
                        "І це кілометри чи милі?" if not has_scale else
                        "Уточніть, будь ласка, пробіг у кілометрах чи милях?")
        if not confirmed:
            # Retain partial units/scale supplied over several messages.
            state["pending_text"] = combined
            return state, question
        state["verified"][pending] = combined
        state["pending_field"] = None
        state["pending_text"] = None
        return state, None

    result = next_clarification(raw)
    if result["pending_field"]:
        state["pending_field"] = result["pending_field"]
        state["pending_text"] = raw
        return state, result["question"]
    return state, None
