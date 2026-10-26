"""Read-only indicative delivery quote from the company's price sheet.

Do not treat a US state, a car model or a budget as an auction location.
Prices here are not a delivered-to-customer quote.
"""
import re
from helpcrunch_shipping_data import RATES

def shipping_context(history):
    if not history:
        return ""
    user_text = " ".join(t.get("content", "") for t in history[-12:]
                         if t.get("role") == "user")
    normalized = re.sub(r"[^A-Z0-9]+", " ", user_text.upper())
    if not normalized.strip():
        return ""
    relevant = ("достав", "shipping", "перевез", "логіст", "транспорту")
    if not any(word in user_text.casefold() for word in relevant):
        return ""
    auction = None
    lowered = user_text.casefold()
    if "copart" in lowered or "копарт" in lowered:
        auction = "Copart"
    elif "iaai" in lowered or "iaa " in lowered:
        auction = "IAAI"
    if not auction:
        return ("Клієнт питає про доставку. Для розрахунку за прайсом спочатку "
                "уточни аукціон Copart чи IAAI та точну локацію лота/місто і штат. "
                "Не називай ціну без цих даних.")
    options = []
    for item in RATES[auction]["locations"]:
        location = re.sub(r"[^A-Z0-9]+", " ", item["location"].upper()).strip()
        if len(location) >= 7 and (" " + location + " ") in (" " + normalized + " "):
            options.append(item)
    if len(options) != 1:
        return ("Для визначення суми за прайсом попроси ТОЧНУ локацію аукціону "
                f"{auction} (як у картці лота). Не оцінюй доставку лише за штатом.")
    location = options[0]
    routes = location["routes"]
    parts = [f"{r['port']}: ${r['price']} (доставка від локації до порту США)" for r in routes]
    return ("ВНУТРІШНІ ДОВІДКОВІ ТАРИФИ, не повна вартість доставки авто в Україну. "
            f"Аукціон {auction}; локація {location['location']}; перевезення до порту: "
            + "; ".join(parts) + ". "
            "Ціни орієнтовні за наявною таблицею без перевіреної дати актуальності. "
            "Портові, морські, митні та інші витрати не включені. "
            "Називай цифри лише із зазначенням їхнього обмеженого обсягу, "
            "а повний кошторис запропонуй уточнити з менеджером.")

def confirmed_route_reply(history):
    """Give a grounded quote deterministically, not at LLM discretion."""
    if not history or history[-1].get("role") != "user":
        return None
    latest = history[-1].get("content", "")
    if not any(word in latest.casefold() for word in ("достав", "shipping", "перевез")):
        return None
    context = shipping_context(history)
    if not context.startswith("ВНУТРІШНІ ДОВІДКОВІ ТАРИФИ"):
        return None
    # Context is derived only from numeric verified sheet rows.
    details = context.split("перевезення до порту: ", 1)[-1].split(". Ціни орієнтовні", 1)[0]
    if not details or "доставка від локації" not in details:
        return None
    details = details.replace(" (доставка від локації до порту США)", "")
    return ("За нашим прайсом перевезення від зазначеної аукціонної локації "
            "до порту відправлення: " + details.rstrip(".") + ". "
            "Це лише наземна доставка до порту, не повна вартість доставки в Україну. "
            "Морське перевезення та інші витрати менеджер розрахує окремо.")
