import json
import re
from urllib.parse import urlparse

from workers import WorkerEntrypoint, Response, fetch
from pricing_data import PRICE_DATA


GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
PRIMARY_MODEL = "openai/gpt-oss-120b"
FALLBACK_MODEL = "openai/gpt-oss-20b"

SYSTEM_PROMPT = """
Ти — AI-консультант автомобільної компанії Auction Auto.

СТИЛЬ:
- Пиши коротко й природно, зазвичай 1–3 речення.
- Звертайся до клієнта на "Ви".
- Відповідай мовою поточного повідомлення клієнта: українською або російською.
- Якщо клієнт поставив конкретне питання — спочатку дай відповідь саме на нього.
- Не перетворюй діалог на анкету й не повторюй уже відомі параметри.

КРИТИЧНО:
- Завжди використовуй переданий ПОТОЧНИЙ КОНТЕКСТ АВТО.
- Якщо клієнт уже назвав марку, модель, рік або привід — не підмінюй їх іншими.
- Якщо контекст BMW 540 2020 AWD, не відповідай характеристиками BMW 540 2023.
- Якщо технічний факт не вдалося надійно перевірити — не вгадуй.
- Не вигадуй актуальні лоти, ціни авто, доставку, порти, строки, комісії чи інші бізнес-умови.
- Не проси номер телефону без природної причини.
- Якщо питають, чи ти бот — чесно скажи, що ти AI-консультант Auction Auto.
""".strip()


TECHNICAL_KEYWORDS = (
    "батар", "квт", "kwh", "ємніст", "емкост", "capacity",
    "двигун", "двигател", "engine", "мотор",
    "короб", "transmission", "cvt", "автомат",
    "потуж", "мощност", "horsepower", "л.с", "к.с",
    "привід", "привод", "awd", "rwd", "fwd", "4wd", "xdrive",
    "запас ходу", "range", "пробег на заряде",
    "розгін", "разгон", "0-100", "0–100", "0-60",
    "комплектац", "trim",
    "роки випуску", "годы выпуска", "model year",
    "рестайл", "facelift",
    "заряд", "charging",
)

QUESTION_MARKERS = (
    "?", "який", "яка", "яке", "які", "скільки",
    "какой", "какая", "какое", "какие", "сколько",
    "what", "which", "how ",
)

BRANDS = {
    "bmw": "BMW", "бмв": "BMW",
    "mercedes-benz": "Mercedes-Benz", "mercedes": "Mercedes-Benz", "мерседес": "Mercedes-Benz",
    "audi": "Audi", "ауди": "Audi",
    "toyota": "Toyota", "тойота": "Toyota",
    "lexus": "Lexus", "лексус": "Lexus",
    "ford": "Ford", "форд": "Ford",
    "chevrolet": "Chevrolet", "шевроле": "Chevrolet",
    "nissan": "Nissan", "ниссан": "Nissan", "ніссан": "Nissan",
    "kia": "Kia", "киа": "Kia", "кіа": "Kia",
    "hyundai": "Hyundai", "хюндай": "Hyundai", "хендай": "Hyundai",
    "honda": "Honda", "хонда": "Honda",
    "subaru": "Subaru", "субару": "Subaru",
    "tesla": "Tesla", "тесла": "Tesla",
    "rivian": "Rivian", "ривиан": "Rivian", "рівіан": "Rivian",
    "porsche": "Porsche", "порше": "Porsche",
    "volkswagen": "Volkswagen", "vw": "Volkswagen", "фольксваген": "Volkswagen",
    "mazda": "Mazda", "мазда": "Mazda",
    "cadillac": "Cadillac", "кадиллак": "Cadillac",
    "jeep": "Jeep", "джип": "Jeep",
    "lincoln": "Lincoln", "лінкольн": "Lincoln", "линкольн": "Lincoln",
}


def normalize(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def detect_language(text: str) -> str:
    low = text.lower()
    ru = sum(x in low for x in (
        "какой", "какая", "сколько", "пробег", "полный привод",
        "двигатель", "комплектация", "интересует",
    ))
    uk = sum(x in low for x in (
        "який", "яка", "скільки", "пробіг", "повний привід",
        "двигун", "комплектація", "цікавить",
    ))
    return "ru" if ru > uk else "uk"


def is_question(text: str) -> bool:
    low = normalize(text).lower()
    return any(marker in low for marker in QUESTION_MARKERS)


def is_technical_question(text: str) -> bool:
    low = normalize(text).lower()
    return is_question(text) and any(k in low for k in TECHNICAL_KEYWORDS)


def clean_citations(text: str) -> str:
    text = re.sub(r"【[^】]*】", "", text)
    text = re.sub(r"\[\d+\s*†\s*L\d+(?:\s*-\s*L?\d+)?\]", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def detect_brand(text: str):
    low = text.lower()
    for alias in sorted(BRANDS, key=len, reverse=True):
        if re.search(rf"(?<![\w]){re.escape(alias)}(?![\w])", low):
            return BRANDS[alias]
    return None


def looks_like_year_only_reply(text: str) -> bool:
    clean = normalize(text).lower()
    return bool(
        re.fullmatch(
            r"(?:19[8-9]\d|20[0-3]\d)(?:\s*\+)?"
            r"(?:\s*[-–—/]\s*(?:19[8-9]\d|20[0-3]\d))?"
            r"(?:\s*(?:рік|року|роки|р\.|год|года|годы))?",
            clean,
        )
    )


def looks_like_mileage_reply(text: str) -> bool:
    low = text.lower()
    return (
        any(x in low for x in ("км", "миль", "mile", "пробіг", "пробег"))
        and bool(re.search(r"\d", low))
    )


def looks_like_budget_reply(text: str) -> bool:
    low = text.lower()
    return (
        any(x in low for x in ("$", "usd", "дол", "бюджет", "під ключ", "под ключ"))
        and bool(re.search(r"\d", low))
    )


def looks_like_consultation_question(text: str) -> bool:
    low = normalize(text).lower()

    if "?" in text:
        return True

    question_starts = (
        "який ", "яка ", "яке ", "які ", "скільки ", "що ", "чим ",
        "чому ", "коли ", "де ", "чи ",
        "какой ", "какая ", "какое ", "какие ", "сколько ", "что ",
        "чем ", "почему ", "когда ", "где ", "есть ли ",
    )

    if any(low.startswith(x) for x in question_starts):
        return True

    consultation_words = (
        "характерист", "комплектац", "двигун", "двигатель", "коробк",
        "батаре", "запас хода", "запас ходу", "надійн", "надежн",
        "ресурс", "різниц", "разниц", "відрізня", "отлича",
        "рестайл", "поколін", "поколен", "вартіст", "стоимост",
        "ціна", "цена",
    )

    return any(word in low for word in consultation_words)


def clean_model_candidate(text: str, brand: str | None = None):
    clean = normalize(text).strip(" ,.!?:;")

    if not clean or len(clean) > 60:
        return None

    if (
        looks_like_year_only_reply(clean)
        or looks_like_mileage_reply(clean)
        or looks_like_budget_reply(clean)
    ):
        return None

    clean = re.sub(
        r"\b(?:19[8-9]\d|20[0-3]\d)(?:\s*\+)?"
        r"(?:\s*[-–—/]\s*(?:19[8-9]\d|20[0-3]\d))?\b",
        " ",
        clean,
    )
    clean = normalize(clean).strip(" ,.!?:;")
    low = clean.lower()

    # Natural client phrases before the model.
    clean = re.sub(
        r"(?i)^(?:"
        r"мене\s+цікавить|меня\s+интересует|"
        r"цікавить|интересует|"
        r"хочу|шукаю|ищу|"
        r"автомобіль|автомобиль|машина|модель"
        r")\s*[,;:\-]?\s*",
        "",
        clean,
    ).strip()

    low = clean.lower()

    if brand:
        for alias, canonical in sorted(
            BRANDS.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            if canonical != brand:
                continue

            clean = re.sub(
                re.escape(alias),
                " ",
                clean,
                flags=re.IGNORECASE,
            )

        clean = normalize(clean).strip(" ,.!?:;")

    if not clean or len(clean.split()) > 4:
        return None

    if not re.search(r"[A-Za-zА-Яа-яЁёІіЇїЄєҐґ0-9]", clean):
        return None

    return clean


def extract_model_from_message(text: str, memory: dict):
    clean = normalize(text)
    brand = memory.get("brand") or detect_brand(clean)
    last_topic = memory.get("last_question_topic")

    # Same principle as the local version:
    # short reply after "which model?" is the model.
    if last_topic == "model" and "?" not in clean:
        return clean_model_candidate(clean, brand)

    detected_brand = detect_brand(clean)

    # Mercedes Benz E-class / BMW 540 / Subaru Crosstrek / ...
    if detected_brand:
        candidate = clean_model_candidate(clean, detected_brand)
        if candidate and candidate.lower() != detected_brand.lower():
            return candidate

    # Brand is known and model is still missing: "G63", "W214", "X5".
    if (
        brand
        and not memory.get("model")
        and not looks_like_consultation_question(clean)
    ):
        return clean_model_candidate(clean, brand)

    return None


def detect_years(text: str):
    # Preserve intent such as "2015+" and "2018-2020".
    plus = re.search(
        r"\b((?:19[8-9]\d|20[0-3]\d))\s*\+",
        text,
    )
    if plus:
        return [f"{plus.group(1)}+"]

    year_range = re.search(
        r"\b((?:19[8-9]\d|20[0-3]\d))\s*[-–—]\s*((?:19[8-9]\d|20[0-3]\d))\b",
        text,
    )
    if year_range:
        return [
            year_range.group(1),
            year_range.group(2),
        ]

    return re.findall(
        r"\b(?:19[8-9]\d|20[0-3]\d)\b",
        text,
    )


def detect_drive(text: str):
    low = text.lower()
    if any(x in low for x in ("повний привід", "полный привод", "awd", "xdrive", "4wd")):
        return "AWD"
    if any(x in low for x in ("задній привід", "задний привод", "rwd")):
        return "RWD"
    if any(x in low for x in ("передній привід", "передний привод", "fwd")):
        return "FWD"
    return None


def detect_mileage(text: str):
    low = text.lower()
    if not any(x in low for x in ("пробіг", "пробег", "км", "миль", "mile")):
        return None

    m = re.search(
        r"(?i)(?:до\s*)?(\d{1,3}(?:[ .]\d{3})+|\d{4,6})\s*(км|миль|miles?|mi)\b",
        text,
    )

    if not m:
        return normalize(text)[:80]

    amount = m.group(1).replace(" ", "")
    unit = m.group(2)
    return f"до {amount} {unit}" if "до" in low else f"{amount} {unit}"


def detect_trim(text: str):
    low = normalize(text).lower()
    markers = (
        "максим", "топ", "предтоп", "пред-топ",
        "base", "базов", "limited", "premium", "sport", "performance",
    )
    if any(x in low for x in markers) and not is_question(text):
        return normalize(text)[:80]
    return None


def detect_budget(text: str):
    low = text.lower()
    if not any(x in low for x in ("бюдж", "$", "дол", "usd", "під ключ", "под ключ")):
        return None

    m = re.search(
        r"(?i)(?:\$\s*)?(\d{1,3}(?:[ .]\d{3})+|\d{4,6})(?:\s*(?:\$|usd|дол(?:ар(?:ів|ов)?)?))?",
        text,
    )
    if not m:
        return normalize(text)[:100]

    amount = m.group(1).replace(" ", "")
    suffix = " під ключ" if "під ключ" in low else (" под ключ" if "под ключ" in low else "")
    return f"${amount}{suffix}"


def detect_engine(text: str):
    low = text.lower()
    if not any(x in low for x in ("двигун", "двигател", "мотор", "бензин", "дизел", "гібрид", "гибрид")):
        return None
    return normalize(text)[:100]


def detect_battery(text: str):
    low = text.lower()
    if not any(x in low for x in ("батар", "квт", "kwh")):
        return None
    return normalize(text)[:100]


def default_state():
    return {
        "selection_offered": False,
        "selection_declined": False,
        "selection_reoffer_pending": False,
        "waiting_for_phone": False,
        "lead_sent": False,
        "do_not_ask_phone": False,
        "phone": None,
        "ended": False,
    }


def is_affirmative(text: str) -> bool:
    low = normalize(text).lower()
    return low in {
        "так", "да", "так давайте", "давайте", "хочу", "цікаво",
        "интересно", "добре", "ок", "окей", "гаразд", "хорошо", "погнали",
        "так, давайте", "да, давайте",
    }


def is_negative(text: str) -> bool:
    low = normalize(text).lower()
    return low in {
        "ні", "нет", "не треба", "не нужно", "поки ні", "пока нет",
        "не цікаво", "не интересно",
    }


def explicitly_wants_selection(text: str) -> bool:
    low = normalize(text).lower()
    phrases = (
        "подбери варианты",
        "подберите варианты",
        "покажи варианты",
        "покажите варианты",
        "хочу варианты",
        "хочу подобрать",
        "хочу підбір",
        "підбери варіанти",
        "підберіть варіанти",
        "покажи варіанти",
        "покажіть варіанти",
        "актуальные лоты",
        "актуальні лоти",
        "актуальные варианты",
        "актуальні варіанти",
        "свяжите с менеджером",
        "зв'яжіть з менеджером",
        "связаться с менеджером",
        "хочу заказать",
        "хочу замовити",
        "замовити авто",
        "заказать авто",
        "готов покупать",
        "готов купувати",
        "хочу розрахунок",
        "хочу расчет",
        "виклик менеджера",
        "вызов менеджера",
    )
    return any(p in low for p in phrases)


def user_forbids_phone_request(text: str) -> bool:
    low = normalize(text).lower()
    phrases = (
        "не проси номер", "не просіть номер", "не просите номер",
        "номер не дам", "не дам номер", "не хочу давати номер",
        "не хочу давать номер",
    )
    return any(p in low for p in phrases)


def looks_like_phone(text: str) -> bool:
    digits = re.sub(r"\D", "", text)
    return 10 <= len(digits) <= 15


def phone_request_text(language: str) -> str:
    if language == "ru":
        return (
            "Хорошо 👍 Оставьте, пожалуйста, номер телефона или нажмите "
            "«📱 Поділитися номером» — передам запрос менеджеру на подбор."
        )
    return (
        "Добре 👍 Залиште, будь ласка, номер телефону або натисніть "
        "«📱 Поділитися номером» — передам запит менеджеру на підбір."
    )


def soft_offer_text(language: str) -> str:
    if language == "ru":
        return (
            "Кстати, если хотите, можем подобрать несколько актуальных вариантов "
            "под эти параметры и показать, что сейчас есть на торгах. Интересно?"
        )
    return (
        "До речі, якщо хочете, можемо підібрати кілька актуальних варіантів "
        "під ці параметри й показати, що зараз є на торгах. Цікаво?"
    )


def is_simple_acknowledgement(text: str) -> bool:
    low = normalize(text).lower().strip(" .,!🙂👍")
    return low in {
        "зрозуміло", "ясно", "ок", "окей", "добре", "гаразд",
        "дякую", "спасибі", "понял", "понятно", "ясно", "хорошо",
        "спасибо",
    }


def core_qualification_ready(memory: dict) -> bool:
    return bool(
        memory.get("brand")
        and memory.get("model")
        and memory.get("years")
        and memory.get("mileage")
        and memory.get("trim")
    )


def next_qualification_reply(memory: dict) -> str | None:
    lang = memory.get("language", "uk")
    brand = memory.get("brand")
    model = memory.get("model")
    years = memory.get("years")
    mileage = memory.get("mileage")
    trim = memory.get("trim")
    vehicle = vehicle_label(memory)

    if brand and not model:
        return (
            f"Яка саме модель {brand} Вас цікавить?"
            if lang == "uk"
            else f"Какая именно модель {brand} Вас интересует?"
        )

    if brand and model and not years:
        return (
            f"Добре, {brand} {model}. Який рік або діапазон років розглядаєте?"
            if lang == "uk"
            else f"Хорошо, {brand} {model}. Какой год или диапазон лет рассматриваете?"
        )

    if brand and model and years and not mileage:
        return (
            f"Добре, орієнтуємося на {vehicle}. По пробігу є побажання?"
            if lang == "uk"
            else f"Хорошо, ориентируемся на {vehicle}. По пробегу есть пожелания?"
        )

    if brand and model and years and mileage and not trim:
        return (
            f"Добре, {vehicle}, пробіг {mileage}. По комплектації є побажання?"
            if lang == "uk"
            else f"Хорошо, {vehicle}, пробег {mileage}. По комплектации есть пожелания?"
        )

    return None


def should_consult_ai(text: str) -> bool:
    # AI is only for a REAL question/consultation request.
    # Bare answers like "2015-2017", "до 200000 км", "максимальна"
    # must never trigger a technical lecture.
    return looks_like_consultation_question(text)


def main_keyboard():
    return {
        "keyboard": [
            [
                {
                    "text": "📱 Поділитися номером",
                    "request_contact": True,
                },
                {
                    "text": "👨‍💼 Виклик менеджера",
                },
            ],
            [
                {
                    "text": "🔄 Почати новий чат",
                },
                {
                    "text": "✅ Завершити чат",
                },
            ],
        ],
        "resize_keyboard": True,
        "input_field_placeholder": "Напишіть повідомлення...",
    }


def detect_question_topic(answer: str):
    questions = re.findall(r"[^?]*\?", answer, flags=re.DOTALL)
    if not questions:
        return None

    q = normalize(questions[-1]).lower()

    priority = (
        ("model", ("модел", "model", "який клас", "какой класс")),
        ("brand", ("марка", "бренд", "brand")),
        ("year", ("який рік", "які роки", "року", "років", "рік", "какой год", "какие годы", "года", "год")),
        ("mileage", ("пробіг", "пробег", "кілометр", "миль")),
        ("trim", ("комплектац", "максимал", "предтоп", "пред-топ", "опції", "опции")),
        ("engine", ("двигун", "двигатель", "мотор", "бензин", "дизел")),
        ("drive", ("привід", "привод", "xdrive", "awd", "fwd", "rwd")),
        ("battery", ("батаре", "квт", "kwh")),
        ("color", ("колір", "цвет")),
        ("budget", ("бюджет", "під ключ", "под ключ")),
    )

    for topic, markers in priority:
        if any(marker in q for marker in markers):
            return topic

    return None


def remember_assistant_question(memory: dict, answer: str):
    asked = list(memory.get("asked_questions") or [])

    for part in re.split(r"(?<=[?])\s+|\n+", answer):
        part = normalize(part)

        if "?" in part and part not in asked:
            asked.append(part)

    memory["asked_questions"] = asked[-14:]
    memory["last_question_topic"] = detect_question_topic(answer)
    return memory


def store_contextual_answer(memory: dict, text: str):
    topic = memory.get("last_question_topic")
    clean = normalize(text)

    if not topic or not clean or "?" in clean or len(clean) > 100:
        return

    if topic == "model":
        candidate = clean_model_candidate(clean, memory.get("brand"))
        if candidate:
            memory["model"] = candidate

    elif topic == "year":
        years = detect_years(clean)
        if years:
            memory["years"] = years

    elif topic == "mileage":
        memory["mileage"] = clean

    elif topic == "trim":
        memory["trim"] = clean

    elif topic == "budget":
        memory["budget"] = clean

    elif topic == "engine":
        memory["engine"] = clean

    elif topic == "drive":
        memory["drive"] = clean

    elif topic == "battery":
        memory["battery"] = clean

    elif topic == "color":
        memory["color"] = clean


def update_memory(memory: dict, text: str):
    memory = dict(memory or {})
    changed = set()

    memory.setdefault("asked_questions", [])
    memory.setdefault("last_question_topic", None)

    # Snapshot slots BEFORE interpreting a short contextual reply.
    # This is critical: if the bot asked for year and client writes "2015-2017",
    # we must both SAVE the years and mark "years" as changed so the deterministic
    # qualification flow advances to mileage instead of sending the reply to Groq.
    tracked_slots = (
        "brand", "model", "years", "budget", "mileage",
        "trim", "engine", "drive", "battery", "color",
    )
    before_context = {
        key: memory.get(key)
        for key in tracked_slots
    }

    store_contextual_answer(memory, text)

    for key in tracked_slots:
        if memory.get(key) != before_context.get(key):
            changed.add(key)

    brand = detect_brand(text)
    if brand and brand != memory.get("brand"):
        memory["brand"] = brand
        changed.add("brand")

    model = extract_model_from_message(text, memory)
    if model and model != memory.get("model"):
        memory["model"] = model
        changed.add("model")

    years = detect_years(text)
    if years and years != memory.get("years"):
        memory["years"] = years
        changed.add("years")

    drive = detect_drive(text)
    if drive and drive != memory.get("drive"):
        memory["drive"] = drive
        changed.add("drive")

    mileage = detect_mileage(text)
    if mileage and mileage != memory.get("mileage"):
        memory["mileage"] = mileage
        changed.add("mileage")

    trim = detect_trim(text)
    if trim and trim != memory.get("trim"):
        memory["trim"] = trim
        changed.add("trim")

    budget = detect_budget(text)
    if budget and budget != memory.get("budget"):
        memory["budget"] = budget
        changed.add("budget")

    engine = detect_engine(text)
    if engine and engine != memory.get("engine"):
        memory["engine"] = engine
        changed.add("engine")

    battery = detect_battery(text)
    if battery and battery != memory.get("battery"):
        memory["battery"] = battery
        changed.add("battery")

    memory["language"] = detect_language(text)

    facts = list(memory.get("client_facts") or [])
    clean = normalize(text)
    if clean and clean not in facts:
        facts.append(clean)
    memory["client_facts"] = facts[-10:]

    return memory, changed


def vehicle_label(memory: dict) -> str:
    parts = []
    if memory.get("brand"):
        parts.append(memory["brand"])
    if memory.get("model"):
        parts.append(memory["model"])
    if memory.get("years"):
        parts.append("-".join(memory["years"]))
    return " ".join(parts).strip()


def qualification_reply(memory: dict, state: dict, changed: set, user_text: str):
    # Explicit client questions go to consultation.
    if should_consult_ai(user_text):
        return None

    # If the client has supplied/updated a qualification slot,
    # always continue the deterministic local flow.
    if changed.intersection({
        "brand", "model", "years", "drive", "mileage",
        "trim", "budget", "engine", "battery", "color"
    }):
        next_reply = next_qualification_reply(memory)
        if next_reply:
            return next_reply

    # Once the basic request is clear, offer selection once.
    if (
        core_qualification_ready(memory)
        and not state.get("lead_sent")
        and not state.get("selection_offered")
        and not state.get("selection_declined")
    ):
        state["selection_offered"] = True
        return soft_offer_text(
            memory.get("language", "uk")
        )

    # For a non-question phrase during qualification, do NOT send it to AI.
    # Repeat only the next logical missing field.
    if not should_consult_ai(user_text):
        return next_qualification_reply(memory)

    return None


def memory_context(memory: dict) -> str:
    fields = []
    for key, label in (
        ("brand", "Марка"),
        ("model", "Модель"),
        ("years", "Рік/роки"),
        ("drive", "Привід"),
        ("mileage", "Пробіг"),
        ("trim", "Комплектація"),
        ("budget", "Бюджет"),
        ("engine", "Двигун"),
        ("battery", "Батарея"),
    ):
        value = memory.get(key)
        if not value:
            continue
        if isinstance(value, list):
            value = ", ".join(value)
        fields.append(f"{label}: {value}")

    if not fields:
        return "ПОТОЧНИЙ КОНТЕКСТ АВТО: ще не визначений."

    return (
        "ПОТОЧНИЙ КОНТЕКСТ АВТО (КРИТИЧНО, НЕ ПІДМІНЮЙ): "
        + "; ".join(fields)
        + ". Для технічної відповіді перевіряй саме цю модель і саме вказаний рік."
    )



def normalize_location_text(text: str) -> str:
    value = normalize(text).upper()
    value = value.replace("–", "-").replace("—", "-")
    value = re.sub(r"[^A-Z0-9\- ]+", " ", value)
    value = value.replace("-", " ")
    return " ".join(value.split())


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


def logistics_needs(text: str) -> set:
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


def format_verified_price(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        if float(value).is_integer():
            return f"${int(value)}"
        return f"${value}"

    if isinstance(value, dict):
        status = value.get("status")

        if status in ("manual_check", "uncertain", "raw_text"):
            return None

        if "min" in value and "max" in value:
            return f"${value['min']}–${value['max']}"

        if "value" in value and isinstance(value["value"], (int, float)):
            return f"${value['value']}"

    return None


def matching_price_locations(text: str):
    """
    Search BOTH Copart and IAAI.
    If client writes only a city such as Chicago and all matching
    auction locations have the same verified tariff, we can safely
    answer without inventing a specific yard.
    """
    search = normalize_location_text(text)
    search_tokens = set(search.split())
    rows = []

    for auction in ("Copart", "IAAI"):
        section = PRICE_DATA.get("usa", {}).get(auction, {})

        for item in section.get("locations", []):
            full_name = str(item.get("location") or "")
            if not full_name:
                continue

            base = full_name.split(" - ")[0].split(" / ")[0].strip()
            base_n = normalize_location_text(base)
            base_tokens = base_n.split()

            score = 0

            if base_n and base_n in search:
                score = 1000 + len(base_n)
            elif base_tokens:
                city_token = base_tokens[0]
                if (
                    len(city_token) >= 4
                    and city_token in search_tokens
                ):
                    score = 100 + len(city_token)

            if score:
                rows.append({
                    "auction": auction,
                    "location": full_name,
                    "score": score,
                    "routes": item.get("routes", []),
                })

    if not rows:
        return []

    best = max(row["score"] for row in rows)

    # Exact / full matches win. For generic city-level match,
    # keep all equal city matches and deduplicate by verified price later.
    if best >= 1000:
        rows = [row for row in rows if row["score"] == best]
    else:
        rows = [row for row in rows if row["score"] >= 100]

    return rows


def vehicle_hint_from_memory(memory: dict) -> str:
    return " ".join(
        str(x)
        for x in (
            memory.get("brand"),
            memory.get("model"),
            (
                "-".join(memory.get("years", []))
                if memory.get("years")
                else None
            ),
        )
        if x
    ).strip()


def obvious_shipping_category(vehicle_text: str):
    low = normalize(vehicle_text).lower()

    small_markers = (
        "sedan", "седан", "coupe", "купе", "hatch", "хетч",
        "wagon", "універсал", "универсал",
        "a4", "a5", "a6", "a7", "a8",
        "3 series", "4 series", "5 series", "7 series",
        "camry", "corolla", "accord", "civic", "k5", "fusion",
        "model 3", "model s",
    )

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
    )

    large_markers = (
        "dually", "over 20", "3500", "4500", "5500",
        "f-350", "f350", "f-450", "f450",
        "silverado 3500", "ram 3500",
    )

    moto_markers = (
        "motorcycle", "мотоцикл", "мото ",
    )

    if any(x in low for x in moto_markers):
        return "Motorcycle"

    if any(x in low for x in large_markers):
        return "Extra Large Vehicle/Dually/Over 20 ft."

    if any(x in low for x in suv_markers):
        return "Crossover/SUV/Standard Truck"

    if any(x in low for x in small_markers):
        return "Small vehicle/Coupe/Sedan"

    return None


async def classify_shipping_category(api_key: str, vehicle_text: str):
    obvious = obvious_shipping_category(vehicle_text)
    if obvious:
        return obvious

    # Internal classifier only. It never calculates a tariff and never
    # sends a technical consultation to the client.
    messages = [
        {
            "role": "system",
            "content": (
                "Classify a vehicle into exactly one shipping category. "
                "Return only one of: SMALL, SUV, LARGE, MOTO. "
                "SMALL = coupe/sedan/hatch/wagon. "
                "SUV = crossover/SUV/standard pickup. "
                "LARGE = dually/extra-large/over 20 ft. "
                "MOTO = motorcycle."
            ),
        },
        {
            "role": "user",
            "content": vehicle_text,
        },
    ]

    try:
        answer = await groq_call(
            api_key,
            FALLBACK_MODEL,
            messages,
            False,
        )
    except Exception:
        return None

    token = normalize(answer).upper()

    mapping = {
        "SMALL": "Small vehicle/Coupe/Sedan",
        "SUV": "Crossover/SUV/Standard Truck",
        "LARGE": "Extra Large Vehicle/Dually/Over 20 ft.",
        "MOTO": "Motorcycle",
    }

    for key, category in mapping.items():
        if key in token:
            return category

    return None


def build_land_logistics_answer(rows: list, language: str):
    verified = []

    for row in rows:
        short = row["location"].split(" - ")[0].strip()

        for route in row.get("routes", []):
            price = format_verified_price(route.get("price"))
            port = route.get("port")

            if price and port:
                verified.append({
                    "auction": row["auction"],
                    "location": short,
                    "port": str(port),
                    "price": price,
                })

    if not verified:
        return None

    unique = {
        (item["port"], item["price"])
        for item in verified
    }

    # Same verified tariff across all matching yards/auctions.
    if len(unique) == 1:
        port, price = next(iter(unique))
        place = verified[0]["location"]

        if language == "ru":
            return (
                f"Для {place} доставка по США до порта {port} — {price}."
            )

        return (
            f"Для {place} доставка по США до порту {port} — {price}."
        )

    # Different tariffs: show them instead of guessing.
    parts = []

    seen = set()

    for item in verified:
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
            f"{item['auction']} {item['location']} — "
            f"{item['price']} до {item['port']}"
        )

    if language == "ru":
        return "Тариф зависит от площадки: " + "; ".join(parts) + "."

    return "Тариф залежить від площадки: " + "; ".join(parts) + "."


async def build_sea_logistics_answer(
    rows: list,
    memory: dict,
    api_key: str,
    language: str,
):
    vehicle = vehicle_hint_from_memory(memory)

    if not vehicle:
        return (
            "Для морського тарифу напишіть модель авто."
            if language == "uk"
            else
            "Для морского тарифа напишите модель автомобиля."
        )

    category = await classify_shipping_category(
        api_key,
        vehicle,
    )

    if not category:
        return (
            "Для морського тарифу уточніть тип авто: "
            "легкове, кросовер/SUV, пікап чи мотоцикл."
            if language == "uk"
            else
            "Для морского тарифа уточните тип авто: "
            "легковое, кроссовер/SUV, пикап или мотоцикл."
        )

    verified = []

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
            sea = format_verified_price(
                rates.get(port)
            )

            if sea and port:
                verified.append({
                    "auction": row["auction"],
                    "port": port,
                    "sea": sea,
                })

    if not verified:
        return None

    unique = {
        (item["port"], item["sea"])
        for item in verified
    }

    if len(unique) == 1:
        port, sea = next(iter(unique))

        if language == "ru":
            return (
                f"Морской тариф через {port} "
                f"для этой категории авто — {sea}."
            )

        return (
            f"Морський тариф через {port} "
            f"для цієї категорії авто — {sea}."
        )

    parts = []

    for item in verified:
        value = (
            item["auction"],
            item["port"],
            item["sea"],
        )

        if value not in parts:
            parts.append(value)

    joined = "; ".join(
        f"{auction} через {port} — {sea}"
        for auction, port, sea in parts
    )

    if language == "ru":
        return "Морской тариф зависит от аукциона: " + joined + "."

    return "Морський тариф залежить від аукціону: " + joined + "."


async def deterministic_logistics_answer(
    user_text: str,
    memory: dict,
    api_key: str,
):
    if not is_logistics_question(user_text):
        return None

    rows = matching_price_locations(user_text)

    if not rows:
        return None

    lang = memory.get("language", "uk")
    needs = logistics_needs(user_text)
    answers = []

    if "land" in needs:
        land = build_land_logistics_answer(
            rows,
            lang,
        )
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

    if "sea" in needs:
        sea = await build_sea_logistics_answer(
            rows,
            memory,
            api_key,
            lang,
        )
        if sea:
            answers.append(sea)

    if answers:
        return " ".join(answers)

    return None


def trim_history(history: list, max_messages: int = 12) -> list:
    result = []
    for item in history[-max_messages:]:
        role = item.get("role")
        content = normalize(item.get("content", ""))
        if role in ("user", "assistant") and content:
            result.append({"role": role, "content": content[:2000]})
    return result


async def ensure_schema(db):
    await db.prepare(
        """
        CREATE TABLE IF NOT EXISTS dialog_state (
            user_id INTEGER PRIMARY KEY,
            chat_id INTEGER NOT NULL,
            history_json TEXT NOT NULL DEFAULT '[]',
            memory_json TEXT NOT NULL DEFAULT '{}',
            state_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    ).run()

    await db.prepare(
        """
        CREATE TABLE IF NOT EXISTS processed_updates (
            update_id INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    ).run()

    await db.prepare(
        """
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            phone TEXT,
            summary TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    ).run()


async def load_state(db, user_id: int):
    row = await db.prepare(
        """
        SELECT history_json, memory_json, state_json
        FROM dialog_state
        WHERE user_id = ?1
        LIMIT 1
        """
    ).bind(user_id).first()

    if not row:
        return [], {}, default_state()

    try:
        history = json.loads(str(row["history_json"]))
    except Exception:
        history = []

    try:
        memory = json.loads(str(row["memory_json"]))
    except Exception:
        memory = {}

    try:
        state = json.loads(str(row["state_json"]))
    except Exception:
        state = {}

    merged_state = default_state()
    merged_state.update(state or {})

    return trim_history(history), memory, merged_state


async def save_state(
    db,
    user_id: int,
    chat_id: int,
    history: list,
    memory: dict,
    state: dict,
):
    history_json = json.dumps(
        trim_history(history),
        ensure_ascii=False,
        separators=(",", ":"),
    )

    memory_json = json.dumps(
        memory,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    state_json = json.dumps(
        state,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    await db.prepare(
        """
        INSERT INTO dialog_state (
            user_id, chat_id, history_json, memory_json, state_json, updated_at
        )
        VALUES (?1, ?2, ?3, ?4, ?5, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            chat_id = excluded.chat_id,
            history_json = excluded.history_json,
            memory_json = excluded.memory_json,
            state_json = excluded.state_json,
            updated_at = CURRENT_TIMESTAMP
        """
    ).bind(
        user_id,
        chat_id,
        history_json,
        memory_json,
        state_json,
    ).run()


async def reset_state(db, user_id: int):
    await db.prepare(
        "DELETE FROM dialog_state WHERE user_id = ?1"
    ).bind(user_id).run()


async def groq_call(api_key: str, model: str, messages: list, browser: bool):
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.15,
        "max_completion_tokens": 320,
        "reasoning_effort": "low",
        "stream": False,
        "citation_options": "disabled",
    }

    if browser:
        payload["tools"] = [{"type": "browser_search"}]
        payload["tool_choice"] = "required"

    response = await fetch(
        GROQ_URL,
        method="POST",
        body=json.dumps(payload, ensure_ascii=False),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    body = await response.text()

    if response.status != 200:
        raise RuntimeError(
            f"Groq {model} HTTP {response.status}: {body[:500]}"
        )

    data = json.loads(body)
    answer = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
        .strip()
    )

    if not answer:
        raise RuntimeError("Groq returned empty answer")

    return clean_citations(answer)


async def ask_groq(api_key: str, history: list, memory: dict, user_text: str):
    browser = is_technical_question(user_text)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": memory_context(memory)},
        *trim_history(history),
        {"role": "user", "content": user_text},
    ]

    try:
        return await groq_call(
            api_key,
            PRIMARY_MODEL,
            messages,
            browser,
        )
    except Exception as primary_error:
        print("PRIMARY GROQ ERROR:", str(primary_error))

    try:
        return await groq_call(
            api_key,
            FALLBACK_MODEL,
            messages,
            browser,
        )
    except Exception as fallback_error:
        print("FALLBACK GROQ ERROR:", str(fallback_error))

    if browser:
        raise RuntimeError("technical verification unavailable")

    return await groq_call(
        api_key,
        FALLBACK_MODEL,
        messages,
        False,
    )


async def send_telegram(
    bot_token: str,
    chat_id: int,
    text: str,
    reply_markup=None,
):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": text,
    }

    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    response = await fetch(
        url,
        method="POST",
        body=json.dumps(
            payload,
            ensure_ascii=False,
        ),
        headers={
            "Content-Type": "application/json",
        },
    )

    body = await response.text()

    if response.status != 200:
        raise RuntimeError(
            f"Telegram sendMessage HTTP {response.status}: {body[:500]}"
        )


def lead_summary(memory: dict) -> str:
    vehicle = " ".join(
        x for x in (
            memory.get("brand"),
            memory.get("model"),
        )
        if x
    ).strip() or "не вказано"

    years = ", ".join(memory.get("years", [])) or "не вказано"
    budget = memory.get("budget") or "не вказано"
    mileage = memory.get("mileage") or "не вказано"
    trim = memory.get("trim") or "не вказано"

    technical = " / ".join(
        x for x in (
            memory.get("engine"),
            memory.get("battery"),
            memory.get("drive"),
        )
        if x
    ) or "не вказано"

    preferences = "; ".join(
        memory.get("client_facts", [])[-6:]
    ) or "не вказано"

    return (
        f"Авто: {vehicle}\n"
        f"Рік: {years}\n"
        f"Бюджет: {budget}\n"
        f"Пробіг: {mileage}\n"
        f"Комплектація: {trim}\n"
        f"Двигун / батарея / привід: {technical}\n"
        f"Побажання: {preferences}"
    )


async def create_lead(
    env,
    sender: dict,
    user_id: int,
    chat_id: int,
    phone: str,
    memory: dict,
    state: dict,
):
    if state.get("lead_sent"):
        return {
            "created": False,
            "admin_sent": True,
            "reason": "already_sent",
        }

    first_name = normalize(sender.get("first_name"))
    last_name = normalize(sender.get("last_name"))
    name = normalize(f"{first_name} {last_name}") or "Без імені"

    username_raw = normalize(sender.get("username"))
    username = f"@{username_raw}" if username_raw else "немає"

    summary = lead_summary(memory)

    # Always save the lead to D1 first.
    await env.DB.prepare(
        """
        INSERT INTO leads (
            user_id,
            chat_id,
            phone,
            summary,
            created_at
        )
        VALUES (?1, ?2, ?3, ?4, CURRENT_TIMESTAMP)
        """
    ).bind(
        user_id,
        chat_id,
        phone,
        summary,
    ).run()

    state["phone"] = phone
    state["waiting_for_phone"] = False
    state["selection_offered"] = False
    state["selection_declined"] = False
    state["selection_reoffer_pending"] = False

    try:
        admin_chat_id = int(
            normalize(str(env.ADMIN_CHAT_ID))
        )
    except Exception:
        admin_chat_id = None

    if not admin_chat_id:
        print("ADMIN LEAD ERROR: ADMIN_CHAT_ID is not configured")
        state["lead_sent"] = False
        state["admin_send_failed"] = True
        return {
            "created": True,
            "admin_sent": False,
            "reason": "admin_not_configured",
        }

    card = (
        "🔥 НОВИЙ ЛІД\n\n"
        f"Ім'я: {name}\n"
        f"Username: {username}\n"
        f"Telegram ID: {user_id}\n"
        f"Телефон: {phone}\n\n"
        f"{summary}"
    )

    try:
        await send_telegram(
            str(env.BOT_TOKEN),
            admin_chat_id,
            card,
        )
    except Exception as error:
        print(
            "ADMIN LEAD SEND ERROR:",
            str(error),
        )
        state["lead_sent"] = False
        state["admin_send_failed"] = True
        return {
            "created": True,
            "admin_sent": False,
            "reason": "telegram_send_failed",
        }

    state["lead_sent"] = True
    state["admin_send_failed"] = False

    return {
        "created": True,
        "admin_sent": True,
        "reason": "sent",
    }


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        path = urlparse(request.url).path

        if path == "/health":
            try:
                await ensure_schema(self.env.DB)
                db_ok = True
            except Exception as error:
                print("D1 HEALTH ERROR:", str(error))
                db_ok = False

            try:
                groq_ok = bool(str(self.env.GROQ_API_KEY))
            except Exception:
                groq_ok = False

            try:
                telegram_ok = bool(str(self.env.BOT_TOKEN))
            except Exception:
                telegram_ok = False

            try:
                admin_ok = bool(str(self.env.ADMIN_CHAT_ID))
            except Exception:
                admin_ok = False

            return Response.json({
                "ok": db_ok and groq_ok and telegram_ok,
                "service": "auction-auto-bot",
                "runtime": "cloudflare-python-worker",
                "d1": db_ok,
                "groq_configured": groq_ok,
                "telegram_configured": telegram_ok,
                "admin_configured": admin_ok,
                "async_webhook": True,
                "lead_flow": True,
                "local_dialog_logic": True,
                "local_qualification_v2": True,
                "strict_local_flow": True,
                "admin_lead_delivery": "configured" if admin_ok else "missing",
                "verified_logistics": True,
            })

        if path != "/telegram-webhook":
            return Response(
                "Auction Auto Worker is running",
                status=200,
            )

        if request.method != "POST":
            return Response(
                "Method Not Allowed",
                status=405,
            )

        try:
            update = await request.json()
        except Exception:
            return Response(
                "Bad Request",
                status=400,
            )

        # Telegram отримує ACK одразу.
        # AI/DB/відповідь клієнту працюють у фоні до 30 секунд.
        self.ctx.waitUntil(
            self.process_update(update)
        )

        return Response.json({"ok": True})

    async def process_update(self, update):
        try:
            await ensure_schema(self.env.DB)

            message = update.get("message")
            if not message:
                return

            chat = message.get("chat") or {}
            sender = message.get("from") or {}

            chat_id = chat.get("id")
            user_id = sender.get("id") or chat_id
            user_text = normalize(message.get("text"))
            contact = message.get("contact") or {}

            if not chat_id or not user_id:
                return

            chat_id = int(chat_id)
            user_id = int(user_id)
            bot_token = str(self.env.BOT_TOKEN)

            if user_text == "/chatid":
                await send_telegram(
                    bot_token,
                    chat_id,
                    f"Chat ID:\n{chat_id}",
                )
                return

            if user_text in ("/start", "/newchat", "/reset", "🔄 Почати новий чат"):
                await reset_state(
                    self.env.DB,
                    user_id,
                )

                await send_telegram(
                    bot_token,
                    chat_id,
                    (
                        "Добре 👍 Починаємо новий діалог. "
                        "Напишіть, яке авто Вас цікавить."
                        if user_text == "🔄 Почати новий чат"
                        else
                        "Добрий день! 👋 Напишіть, яке авто Вас цікавить — "
                        "допоможу зорієнтуватися."
                    ),
                    reply_markup=main_keyboard(),
                )
                return

            history, memory, state = await load_state(
                self.env.DB,
                user_id,
            )

            if user_text == "✅ Завершити чат":
                state["ended"] = True
                await save_state(
                    self.env.DB,
                    user_id,
                    chat_id,
                    history,
                    memory,
                    state,
                )
                await send_telegram(
                    bot_token,
                    chat_id,
                    "Чат завершено. Якщо захочете продовжити — натисніть «🔄 Почати новий чат».",
                    reply_markup=main_keyboard(),
                )
                return

            if state.get("ended"):
                await send_telegram(
                    bot_token,
                    chat_id,
                    "Цей діалог завершено. Натисніть «🔄 Почати новий чат», щоб продовжити.",
                    reply_markup=main_keyboard(),
                )
                return

            phone = normalize(contact.get("phone_number"))
            if phone:
                lead_result = await create_lead(
                    self.env,
                    sender,
                    user_id,
                    chat_id,
                    phone,
                    memory,
                    state,
                )

                await save_state(
                    self.env.DB,
                    user_id,
                    chat_id,
                    history,
                    memory,
                    state,
                )

                if lead_result.get("admin_sent"):
                    lead_answer = (
                        "Дякую 👍 Передам Ваш контакт менеджеру. "
                        "Він перегляне актуальні варіанти та зв'яжеться з Вами."
                        if lead_result.get("created")
                        else
                        "Ваш контакт уже передано менеджеру 👍 Можемо продовжити консультацію."
                    )
                else:
                    lead_answer = (
                        "Дякую 👍 Контакт збережено. "
                        "Автоматична передача в групу менеджерів зараз не спрацювала — "
                        "я залишив лід у системі для повторної відправки."
                    )

                await send_telegram(
                    bot_token,
                    chat_id,
                    lead_answer,
                    reply_markup=main_keyboard(),
                )
                return

            if not user_text:
                await send_telegram(
                    bot_token,
                    chat_id,
                    "Поки що напишіть запит текстом 🙂",
                    reply_markup=main_keyboard(),
                )
                return

            if user_forbids_phone_request(user_text):
                state["do_not_ask_phone"] = True
                state["waiting_for_phone"] = False

            if (
                state.get("selection_offered")
                and should_consult_ai(user_text)
                and not state.get("lead_sent")
            ):
                state["selection_offered"] = False
                state["selection_reoffer_pending"] = True

            if user_text == "👨‍💼 Виклик менеджера":
                if state.get("lead_sent"):
                    answer = "Ваш контакт уже передано менеджеру 👍"
                elif state.get("do_not_ask_phone"):
                    answer = "Добре. Можемо продовжити консультацію тут — номер просити не буду."
                else:
                    state["waiting_for_phone"] = True
                    state["selection_offered"] = False
                    answer = phone_request_text(
                        memory.get("language", "uk")
                    )

                await save_state(
                    self.env.DB,
                    user_id,
                    chat_id,
                    history,
                    memory,
                    state,
                )
                await send_telegram(
                    bot_token,
                    chat_id,
                    answer,
                    reply_markup=main_keyboard(),
                )
                return

            if user_text == "📱 Поділитися номером":
                if state.get("lead_sent"):
                    answer = "Ваш контакт уже передано менеджеру 👍"
                else:
                    state["waiting_for_phone"] = True
                    answer = phone_request_text(
                        memory.get("language", "uk")
                    )

                await save_state(
                    self.env.DB,
                    user_id,
                    chat_id,
                    history,
                    memory,
                    state,
                )
                await send_telegram(
                    bot_token,
                    chat_id,
                    answer,
                    reply_markup=main_keyboard(),
                )
                return

            if state.get("waiting_for_phone") and looks_like_phone(user_text):
                lead_result = await create_lead(
                    self.env,
                    sender,
                    user_id,
                    chat_id,
                    user_text,
                    memory,
                    state,
                )

                await save_state(
                    self.env.DB,
                    user_id,
                    chat_id,
                    history,
                    memory,
                    state,
                )

                if lead_result.get("admin_sent"):
                    lead_answer = (
                        "Дякую 👍 Передам Ваш контакт менеджеру."
                        if lead_result.get("created")
                        else
                        "Ваш контакт уже передано менеджеру 👍 Можемо продовжити консультацію."
                    )
                else:
                    lead_answer = (
                        "Дякую 👍 Контакт збережено. "
                        "Автоматична передача в групу менеджерів зараз не спрацювала — "
                        "лід залишився збереженим у системі."
                    )

                await send_telegram(
                    bot_token,
                    chat_id,
                    lead_answer,
                    reply_markup=main_keyboard(),
                )
                return

            if state.get("selection_offered") and is_affirmative(user_text):
                state["selection_offered"] = False
                state["selection_declined"] = False
                state["selection_reoffer_pending"] = False

                if state.get("lead_sent"):
                    answer = "Ваш контакт уже передано менеджеру 👍 Можемо продовжити консультацію."
                elif state.get("do_not_ask_phone"):
                    answer = (
                        "Добре 👍 Можемо продовжити консультацію тут. "
                        "Якщо самі захочете зв'язок із менеджером — скажіть."
                    )
                else:
                    state["waiting_for_phone"] = True
                    answer = phone_request_text(
                        memory.get("language", "uk")
                    )

                await save_state(
                    self.env.DB,
                    user_id,
                    chat_id,
                    history,
                    memory,
                    state,
                )
                await send_telegram(
                    bot_token,
                    chat_id,
                    answer,
                    reply_markup=main_keyboard(),
                )
                return

            if state.get("selection_offered") and is_negative(user_text):
                state["selection_offered"] = False
                state["selection_declined"] = True
                state["selection_reoffer_pending"] = False

                await save_state(
                    self.env.DB,
                    user_id,
                    chat_id,
                    history,
                    memory,
                    state,
                )

                await send_telegram(
                    bot_token,
                    chat_id,
                    (
                        "Добре 👍 Тоді продовжимо консультацію без підбору."
                        if memory.get("language", "uk") == "uk"
                        else "Хорошо 👍 Тогда продолжим консультацию без подбора."
                    ),
                    reply_markup=main_keyboard(),
                )
                return

            if (
                explicitly_wants_selection(user_text)
                and not state.get("lead_sent")
                and not state.get("do_not_ask_phone")
            ):
                state["waiting_for_phone"] = True
                state["selection_offered"] = False
                state["selection_declined"] = False
                state["selection_reoffer_pending"] = False

                await save_state(
                    self.env.DB,
                    user_id,
                    chat_id,
                    history,
                    memory,
                    state,
                )

                await send_telegram(
                    bot_token,
                    chat_id,
                    phone_request_text(
                        memory.get("language", "uk")
                    ),
                    reply_markup=main_keyboard(),
                )
                return

            if state.get("waiting_for_phone") and is_affirmative(user_text):
                await send_telegram(
                    bot_token,
                    chat_id,
                    (
                        "Надішліть, будь ласка, Ваш номер телефону або натисніть "
                        "«📱 Поділитися номером»."
                        if memory.get("language", "uk") == "uk"
                        else "Пришлите, пожалуйста, Ваш номер телефона или нажмите "
                        "«📱 Поділитися номером»."
                    ),
                    reply_markup=main_keyboard(),
                )
                return

            if (
                is_simple_acknowledgement(user_text)
                and core_qualification_ready(memory)
                and not state.get("lead_sent")
                and not state.get("selection_offered")
                and not state.get("selection_declined")
                and not state.get("waiting_for_phone")
            ):
                state["selection_offered"] = True
                state["selection_reoffer_pending"] = False

                await save_state(
                    self.env.DB,
                    user_id,
                    chat_id,
                    history,
                    memory,
                    state,
                )

                await send_telegram(
                    bot_token,
                    chat_id,
                    soft_offer_text(
                        memory.get("language", "uk")
                    ),
                    reply_markup=main_keyboard(),
                )
                return

            memory, changed = update_memory(
                memory,
                user_text,
            )

            history_with_user = [
                *history,
                {
                    "role": "user",
                    "content": user_text,
                },
            ]

            await save_state(
                self.env.DB,
                user_id,
                chat_id,
                history_with_user,
                memory,
                state,
            )

            logistics_answer = await deterministic_logistics_answer(
                user_text,
                memory,
                str(self.env.GROQ_API_KEY),
            )

            if logistics_answer:
                if (
                    core_qualification_ready(memory)
                    and not state.get("lead_sent")
                ):
                    state["selection_reoffer_pending"] = True
                    state["selection_offered"] = False

                memory = remember_assistant_question(
                    memory,
                    logistics_answer,
                )

                final_history = [
                    *history_with_user,
                    {
                        "role": "assistant",
                        "content": logistics_answer,
                    },
                ]

                await save_state(
                    self.env.DB,
                    user_id,
                    chat_id,
                    final_history,
                    memory,
                    state,
                )

                await send_telegram(
                    bot_token,
                    chat_id,
                    logistics_answer,
                    reply_markup=main_keyboard(),
                )
                return

            deterministic = qualification_reply(
                memory,
                state,
                changed,
                user_text,
            )

            if deterministic:
                answer = deterministic

            elif not should_consult_ai(user_text):
                answer = (
                    next_qualification_reply(memory)
                    or (
                        soft_offer_text(memory.get("language", "uk"))
                        if core_qualification_ready(memory)
                        and not state.get("lead_sent")
                        and not state.get("selection_declined")
                        else
                        (
                            "Добре. Можете уточнити, що саме Вас цікавить по цьому авто?"
                            if memory.get("language", "uk") == "uk"
                            else
                            "Хорошо. Можете уточнить, что именно Вас интересует по этому авто?"
                        )
                    )
                )

                if (
                    answer == soft_offer_text(memory.get("language", "uk"))
                    and not state.get("selection_offered")
                ):
                    state["selection_offered"] = True

            else:
                try:
                    answer = await ask_groq(
                        str(self.env.GROQ_API_KEY),
                        history,
                        memory,
                        user_text,
                    )
                except Exception as error:
                    print(
                        "MESSAGE PROCESSING ERROR:",
                        str(error),
                    )

                    if is_technical_question(user_text):
                        answer = (
                            "Не хочу називати характеристику навмання: "
                            "зараз не вдалося надійно перевірити технічні дані. "
                            "Ваш контекст авто збережений — спробуйте повторити питання трохи пізніше."
                        )
                    else:
                        answer = (
                            "Зараз AI тимчасово недоступний, але Ваші параметри вже збережені. "
                            "Можете продовжувати діалог або повторити повідомлення трохи пізніше."
                        )

            memory = remember_assistant_question(
                memory,
                answer,
            )

            final_history = [
                *history_with_user,
                {
                    "role": "assistant",
                    "content": answer,
                },
            ]

            await save_state(
                self.env.DB,
                user_id,
                chat_id,
                final_history,
                memory,
                state,
            )

            await send_telegram(
                bot_token,
                chat_id,
                answer,
                reply_markup=main_keyboard(),
            )

        except Exception as error:
            print(
                "BACKGROUND PROCESS ERROR:",
                str(error),
            )

