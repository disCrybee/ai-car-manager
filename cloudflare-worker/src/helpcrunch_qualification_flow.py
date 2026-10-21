"""Deterministic, no-network clarification flow for HelpCrunch.

A field is never considered confirmed without explicit units.
This module does not write any data or send chat messages.
"""
import re
from helpcrunch_qualify import qualification_question

CURRENCY = re.compile(r"(?<!\w)(грн|₴|uah|usd|долар(?:ів|и)?|дол|\$|євро|eur|€)(?!\w)", re.I)
MILEAGE_UNIT = re.compile(r"(?<!\w)(км|km|миль|милі|miles?|mi)(?!\w)", re.I)
THOUSANDS = re.compile(r"тисяч|тис\.?|thousand|\bk\b", re.I)


def next_clarification(text: str, expected: str | None = None) -> dict:
    """Give one clarification and the pending field, never inferred values.

    Caller should persist pending_field per HelpCrunch chat and re-run after reply.
    When both budget and mileage appear, budget is clarified first.
    """
    if not isinstance(text, str):
        raise ValueError("Text required")
    if expected not in (None, "budget", "mileage"):
        raise ValueError("Unknown pending field")
    if expected:
        if expected == "budget":
            if CURRENCY.search(text):
                return {"pending_field": None, "confirmed_field": "budget", "question": None}
            return {"pending_field": "budget", "confirmed_field": None,
                    "question": "Уточніть, будь ласка, валюту бюджету: гривні, долари США чи євро?"}
        if MILEAGE_UNIT.search(text) and (re.search(r"\d", text) or THOUSANDS.search(text)):
            return {"pending_field": None, "confirmed_field": "mileage", "question": None}
        return {"pending_field": "mileage", "confirmed_field": None,
                "question": "Уточніть пробіг: скільки саме та у кілометрах чи милях?"}
    for field in ("budget", "mileage"):
        question = qualification_question(text, field=field)
        if question:
            return {"pending_field": field, "confirmed_field": None, "question": question}
    return {"pending_field": None, "confirmed_field": None, "question": None}
