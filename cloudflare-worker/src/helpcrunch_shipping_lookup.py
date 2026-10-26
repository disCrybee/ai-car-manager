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
    """Deterministic separate land and Klaipeda port tariff figures."""
    if not history or history[-1].get("role") != "user":
        return None
    latest = history[-1].get("content", "")
    if not any(word in latest.casefold() for word in ("достав", "shipping", "перевез")):
        return None
    user_text = " ".join(t.get("content", "") for t in history[-12:]
                         if t.get("role") == "user")
    text = re.sub(r"[^A-Z0-9]+", " ", user_text.upper())
    lower = user_text.casefold()
    auction = "Copart" if "copart" in lower or "копарт" in lower else (
        "IAAI" if "iaai" in lower or "iaa " in lower else None)
    if not auction:
        return None
    matched = []
    for item in RATES[auction]["locations"]:
        name = re.sub(r"[^A-Z0-9]+", " ", item["location"].upper()).strip()
        if len(name) >= 7 and (" " + name + " ") in (" " + text + " "):
            matched.append(item)
    if len(matched) != 1 or len(matched[0]["routes"]) != 1:
        return None
    location = matched[0]
    route = location["routes"][0]
    port = route["port"]
    inland = route["price"]
    rates = RATES[auction]["vehicle_rates"]
    sedan = rates["Small vehicle/Coupe/Sedan"].get(port)
    suv = rates["Crossover/SUV/Standard Truck"].get(port)
    if not all(isinstance(v, (int, float)) for v in (inland, sedan, suv)):
        return None
    # A clearly named passenger car does not need irrelevant SUV prices.
    latest_lower = latest.casefold()
    passenger = any(word in latest_lower for word in ("легков", "седан", "sedan", "coupe", "купе"))
    if passenger:
        return (f"З Copart {location['location']} до порту {port} наземна доставка — "
                f"${inland}, далі до Клайпеди за тарифом для легкового авто — "
                f"${sedan}. Разом орієнтовно ${inland + sedan} за дві ділянки. "
                "Це вартість лише доставки суша + море до Клайпеди. "
                "Комплекс послуг, митне оформлення та інші витрати розраховуються окремо.")
    return (
        f"За нашим прайсом для {auction} {location['location']}: "
        f"наземна доставка до порту {port} — ${inland}. "
        f"Тариф від {port} до Клайпеди для легкового авто — ${sedan}, "
        f"для SUV/кросовера — ${suv}. "
        f"Разом ці дві складові: ${inland + sedan} для легкового "
        f"або ${inland + suv} для SUV. "
        "Точну категорію авто потрібно підтвердити; для електро/гібридів "
        "та інших випадків можуть діяти додаткові збори. "
        "Це вартість лише доставки суша + море до Клайпеди. "
        "Комплекс послуг, митне оформлення та інші витрати розраховуються окремо."
    )
