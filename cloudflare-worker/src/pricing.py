import re

from pricing_data import PRICE_DATA
from utils import normalize
from vehicle_logic import next_question, normalize_memory, vehicle_label


def is_turnkey_price_question(text: str) -> bool:
    low = normalize(text).lower()

    price_words = (
        "вартість", "ціна", "скільки", "стоимость", "цена", "price",
    )
    turnkey_words = (
        "під ключ", "под ключ", "в україні", "в украине",
        "пригін", "пригон",
    )

    return (
        any(x in low for x in price_words)
        and any(x in low for x in turnkey_words)
    )


def turnkey_price_answer(memory: dict):
    data = normalize_memory(memory)
    lang = data.get("language") or "uk"
    vehicle = vehicle_label(data) or (
        "цього авто" if lang == "uk" else "этого авто"
    )

    topic, missing_question = next_question(data)

    if lang == "ru":
        base = (
            f"Точную стоимость {vehicle} под ключ можно посчитать только по конкретному лоту: "
            "она зависит от цены покупки, повреждения, локации, доставки и растаможки."
        )
    else:
        base = (
            f"Точну вартість {vehicle} під ключ можна порахувати лише по конкретному лоту: "
            "вона залежить від ціни покупки, пошкодження, локації, доставки та розмитнення."
        )

    if missing_question:
        return base + " " + missing_question, topic

    return base, None


def is_service_fee_question(text: str) -> bool:
    low = normalize(text).lower()
    return any(
        phrase in low
        for phrase in (
            "ваші послуги", "ваши услуги", "вартість послуг", "стоимость услуг",
            "комісія компанії", "комиссия компании", "скільки берете", "сколько берете",
            "ваша комісія", "ваша комиссия",
        )
    )


def _extract_auction_purchase_price(text: str):
    clean = normalize(text)
    low = clean.lower()

    if not any(
        marker in low
        for marker in ("аукціон", "аукцион", "купівл", "покупк", "ставк", "bid", "buy now")
    ):
        return None

    match = re.search(
        r"(?i)(?:\$\s*)?(\d{1,3}(?:[ .]\d{3})+|\d{4,6})\s*(?:\$|usd|дол(?:ар(?:ів|ов)?)?)?",
        clean,
    )
    if not match:
        return None

    try:
        return float(match.group(1).replace(" ", "").replace(".", ""))
    except Exception:
        return None


def company_service_fee(purchase_price: float):
    if purchase_price < 20000:
        return 750
    if purchase_price < 30000:
        return 1000
    return 1500


def service_fee_answer(text: str, memory: dict):
    if not is_service_fee_question(text):
        return None

    data = normalize_memory(memory)
    lang = data.get("language") or "uk"

    price = _extract_auction_purchase_price(text)

    if price is None:
        stored = data.get("auction_purchase_price")
        if isinstance(stored, (int, float)):
            price = float(stored)

    if price is None:
        return (
            "Підкажіть вартість покупки авто на аукціоні — від неї залежить тариф наших послуг."
            if lang == "uk"
            else
            "Подскажите стоимость покупки авто на аукционе — от неё зависит тариф наших услуг."
        )

    fee = company_service_fee(price)

    return (
        f"При вартості покупки ${int(price):,} на аукціоні послуги Auction Auto — ${fee}."
        if lang == "uk"
        else
        f"При стоимости покупки ${int(price):,} на аукционе услуги Auction Auto — ${fee}."
    ).replace(",", " ")


def is_logistics_question(text: str) -> bool:
    low = normalize(text).lower()
    return any(
        marker in low
        for marker in (
            "достав", "логіст", "логист", "shipping",
            "по сша", "по америк", "по штат",
            "суш", "мор", "порт",
        )
    )


def logistics_needs(text: str):
    low = normalize(text).lower()
    needs = set()

    if (
        "суш" in low
        or "по сша" in low
        or "по америк" in low
        or "по штат" in low
    ):
        needs.add("land")

    if "мор" in low:
        needs.add("sea")

    if "порт" in low:
        needs.add("port")

    if (
        "достав" in low
        or "логіст" in low
        or "логист" in low
        or "shipping" in low
    ) and not needs:
        needs.add("land")

    return needs


def _normalize_location(text: str) -> str:
    value = normalize(text).upper()
    value = value.replace("–", "-").replace("—", "-")
    value = re.sub(r"[^A-Z0-9\- ]+", " ", value)
    value = value.replace("-", " ")
    return " ".join(value.split())


def _location_rows(query: str):
    search = _normalize_location(query)
    tokens = set(search.split())
    matches = []

    for auction in ("Copart", "IAAI"):
        section = PRICE_DATA.get("usa", {}).get(auction, {})

        for item in section.get("locations", []):
            full = str(item.get("location") or "")
            if not full:
                continue

            base = full.split(" - ")[0].split(" / ")[0].strip()
            base_n = _normalize_location(base)
            base_tokens = base_n.split()
            score = 0

            if base_n and base_n in search:
                score = 1000 + len(base_n)
            elif base_tokens:
                city = base_tokens[0]
                if len(city) >= 4 and city in tokens:
                    score = 100 + len(city)

            if score:
                matches.append({
                    "auction": auction,
                    "location": full,
                    "routes": item.get("routes", []),
                    "score": score,
                })

    if not matches:
        return []

    best = max(item["score"] for item in matches)

    if best >= 1000:
        return [item for item in matches if item["score"] == best]

    return [item for item in matches if item["score"] >= 100]


def _format_price(value):
    if isinstance(value, (int, float)):
        number = int(value) if float(value).is_integer() else value
        return f"${number}"

    if isinstance(value, dict):
        if value.get("status") in ("manual_check", "uncertain", "raw_text"):
            return None

        if isinstance(value.get("value"), (int, float)):
            return f"${value['value']}"

        if isinstance(value.get("min"), (int, float)) and isinstance(value.get("max"), (int, float)):
            return f"${value['min']}–${value['max']}"

    return None


def _land_answer(rows: list, language: str):
    data = []

    for row in rows:
        short = row["location"].split(" - ")[0].strip()

        for route in row.get("routes", []):
            price = _format_price(route.get("price"))
            port = str(route.get("port") or "")

            if price and port:
                data.append({
                    "auction": row["auction"],
                    "location": short,
                    "port": port,
                    "price": price,
                })

    if not data:
        return None

    unique_tariffs = {
        (item["port"], item["price"])
        for item in data
    }

    if len(unique_tariffs) == 1:
        port, price = next(iter(unique_tariffs))
        city = data[0]["location"].split(" ")[0].title()

        if language == "ru":
            return f"Доставка по США из {city} до порта {port} — {price}."

        return f"Доставка по США з {city} до порту {port} — {price}."

    seen = set()
    parts = []

    for item in data:
        key = (
            item["auction"],
            item["location"],
            item["port"],
            item["price"],
        )

        if key in seen:
            continue
        seen.add(key)

        parts.append(
            f"{item['auction']} {item['location']} — {item['price']} до {item['port']}"
        )

    return (
        "Тариф залежить від конкретної площадки: " + "; ".join(parts) + "."
        if language == "uk"
        else
        "Тариф зависит от конкретной площадки: " + "; ".join(parts) + "."
    )


def obvious_vehicle_category(memory: dict):
    data = normalize_memory(memory)
    low = " ".join(
        str(x or "")
        for x in (
            data.get("brand"),
            data.get("model"),
            data.get("body_type"),
        )
    ).lower()

    if any(x in low for x in ("motorcycle", "мотоцикл", "мото ")):
        return "Motorcycle"

    if any(
        x in low
        for x in (
            "dually", "3500", "4500", "5500", "f-350", "f350", "f-450", "f450",
            "silverado 3500", "ram 3500",
        )
    ):
        return "Extra Large Vehicle/Dually/Over 20 ft."

    suv_markers = (
        "suv", "кросовер", "кроссовер",
        "escalade", "corsair", "aviator", "navigator",
        "rav4", "highlander", "crosstrek", "forester", "outback",
        "rogue", "murano", "pathfinder", "ariya",
        "edge", "escape", "explorer", "bronco",
        "cherokee", "grand cherokee", "wrangler",
        "x1", "x2", "x3", "x4", "x5", "x6", "x7", "xm",
        "glc", "gle", "gls", "g63", "g550", "g-class", "g class",
        "q3", "q5", "q7", "q8", "e-tron", "etron",
        "tucson", "santa fe", "palisade", "ioniq 5",
        "sportage", "sorento", "telluride", "niro", "ev6", "ev9",
        "cx-30", "cx-5", "cx-50", "cx-9", "cx-90",
        "id.4", "tiguan", "touareg",
        "model y", "model x", "r1s",
        "cr-v", "pilot", "passport", "mdx", "rdx",
    )

    if any(x in low for x in suv_markers):
        return "Crossover/SUV/Standard Truck"

    small_markers = (
        "sedan", "седан", "coupe", "купе", "hatch", "хетч", "wagon",
        "універсал", "универсал",
        "a3", "a4", "a5", "a6", "a7", "a8",
        "3 series", "4 series", "5 series", "7 series",
        "camry", "corolla", "accord", "civic", "k5", "fusion",
        "model 3", "model s", "e-class", "c-class", "s-class",
    )

    if any(x in low for x in small_markers):
        return "Small vehicle/Coupe/Sedan"

    return None


def _sea_answer(rows: list, category: str, language: str):
    data = []

    for row in rows:
        rates = (
            PRICE_DATA
            .get("usa", {})
            .get(row["auction"], {})
            .get("vehicle_rates", {})
            .get(category, {})
        )

        for route in row.get("routes", []):
            port = str(route.get("port") or "")
            sea = _format_price(rates.get(port))

            if port and sea:
                data.append({
                    "auction": row["auction"],
                    "port": port,
                    "sea": sea,
                })

    if not data:
        return None

    unique = {
        (item["port"], item["sea"])
        for item in data
    }

    if len(unique) == 1:
        port, sea = next(iter(unique))

        return (
            f"Морський тариф через {port} для цієї категорії авто — {sea}."
            if language == "uk"
            else
            f"Морской тариф через {port} для этой категории авто — {sea}."
        )

    parts = []
    seen = set()

    for item in data:
        key = (item["auction"], item["port"], item["sea"])
        if key in seen:
            continue
        seen.add(key)
        parts.append(
            f"{item['auction']} через {item['port']} — {item['sea']}"
        )

    return (
        "Морський тариф залежить від аукціону: " + "; ".join(parts) + "."
        if language == "uk"
        else
        "Морской тариф зависит от аукциона: " + "; ".join(parts) + "."
    )


def logistics_context(text: str, memory: dict):
    data = normalize_memory(memory)

    rows = _location_rows(text)
    location_source = normalize(text)

    if not rows and data.get("logistics_location"):
        rows = _location_rows(data["logistics_location"])
        location_source = data["logistics_location"]

    if rows:
        # Keep a generic reusable location hint for follow-up "а по морю?".
        first_location = rows[0]["location"].split(" - ")[0].replace("-", " ")
        data["logistics_location"] = first_location

    return rows, data, location_source


def answer_logistics(
    text: str,
    memory: dict,
    *,
    body_category: str | None = None,
):
    if not is_logistics_question(text):
        return None, normalize_memory(memory), False

    data = normalize_memory(memory)
    lang = data.get("language") or "uk"
    needs = logistics_needs(text)

    rows, data, _ = logistics_context(text, data)

    if not rows:
        return (
            (
                "Напишіть аукціон і точну локацію авто — перевірю доставку по нашій тарифній базі."
                if lang == "uk"
                else
                "Напишите аукцион и точную локацию авто — проверю доставку по нашей тарифной базе."
            ),
            data,
            True,
        )

    answers = []

    if "land" in needs:
        land = _land_answer(rows, lang)
        if land:
            answers.append(land)

    if "port" in needs and "land" not in needs:
        ports = []
        for row in rows:
            for route in row.get("routes", []):
                port = route.get("port")
                if port and port not in ports:
                    ports.append(port)

        if ports:
            answers.append(
                (
                    "Відправка йде через " + ", ".join(ports) + "."
                    if lang == "uk"
                    else
                    "Отправка идёт через " + ", ".join(ports) + "."
                )
            )

    needs_body_category = False

    if "sea" in needs:
        category = body_category or obvious_vehicle_category(data)
        if not category:
            needs_body_category = True
        else:
            sea = _sea_answer(rows, category, lang)
            if sea:
                answers.append(sea)

    if needs_body_category and not answers:
        return (
            (
                "Для морського тарифу уточніть тип авто: легкове, кросовер/SUV, пікап чи мотоцикл."
                if lang == "uk"
                else
                "Для морского тарифа уточните тип авто: легковое, кроссовер/SUV, пикап или мотоцикл."
            ),
            data,
            True,
        )

    if answers:
        return " ".join(answers), data, needs_body_category

    return (
        (
            "По цій локації тариф потрібно уточнити."
            if lang == "uk"
            else
            "По этой локации тариф нужно уточнить."
        ),
        data,
        True,
    )
