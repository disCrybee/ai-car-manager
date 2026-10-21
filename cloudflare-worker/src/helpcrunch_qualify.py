"""Conservative qualification parsing for HelpCrunch.

Never infer currency or mileage unit for unspecified numbers.
"""
import re

MONEY = re.compile(r"(?<!\w)(\d[\d\s.,]*)(?:\s*(грн|₴|uah|usd|долар(?:ів|и)?|дол|\$|євро|eur|€))?(?!\w)", re.I)
MILEAGE_CONTEXT = re.compile(r"пробіг|пробег|кілометраж|mileage", re.I)
BUDGET_CONTEXT = re.compile(r"бюджет|вартіст|ціна|цікавить за|до\s*[\d., ]+\s*(?:грн|₴|\$|usd|uah)", re.I)


def _quantity(value):
    s = re.sub(r"\s+", "", value)
    if not re.fullmatch(r"\d[\d.,]*", s):
        return None
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", s):
        return int(re.sub(r"[.,]", "", s))
    if re.fullmatch(r"\d+(?:[.,]\d+)?", s):
        number = float(s.replace(",", "."))
        return int(number) if number.is_integer() else number
    return None


def qualification_question(text: str, *, field: str):
    """Return a clarification, or None when input is sufficiently explicit."""
    value = text.strip()
    if field == "budget":
        if not BUDGET_CONTEXT.search(value) and not re.fullmatch(r"[\d\s.,]+", value):
            return None
        matches = list(MONEY.finditer(value))
        if not matches:
            return None
        last = matches[-1]
        if _quantity(last.group(1)) is None:
            return None
        if last.group(2) or re.search(r"(?<!\\w)(?:[$€₴]|usd|uah|eur|грн|долар(?:ів|и)?|євро)\\s*\\d", value, re.I):
            return None
        return "Підкажіть, будь ласка, бюджет Ви вказали в гривнях, доларах США чи євро?"
    if field == "mileage":
        if not MILEAGE_CONTEXT.search(value) and not re.fullmatch(r"[\d\s.,]+", value):
            return None
        if re.search(r"(?<!\w)(км|km|миль|милі|miles?|mi)(?!\w)", value, re.I):
            return None
        if not re.search(r"\d", value):
            return None
        if re.search(r"тисяч|тис\\.?|thousand|\\bk\\b", value, re.I):
            return "Уточніть, будь ласка, пробіг указаний у кілометрах чи милях?"
        return (
            "Уточніть, будь ласка, пробіг: Ви маєте на увазі "
            "кілометри чи милі? І «100» — це 100 чи 100 тисяч?"
        )
    raise ValueError("Unknown qualification field")
