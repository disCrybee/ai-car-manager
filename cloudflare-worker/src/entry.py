import json
import re
from urllib.parse import urlparse

from workers import WorkerEntrypoint, Response, fetch


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


def detect_model(text: str, brand: str | None):
    clean = normalize(text)

    if brand == "BMW":
        m = re.search(
            r"(?i)\b(?:BMW\s*)?(XM|X[1-7]|i[357X]|M[23458]|[1-8]\d{2}[a-z]{0,3})\b",
            clean,
        )
        if m:
            value = m.group(1)
            return value.upper() if value.lower().startswith(("x", "m")) else value

    if brand == "Tesla":
        m = re.search(r"(?i)\bModel\s*(3|S|X|Y)\b", clean)
        if m:
            return f"Model {m.group(1).upper()}"

    if brand == "Rivian":
        m = re.search(r"(?i)\b(R1S|R1T|R2|R3)\b", clean)
        if m:
            return m.group(1).upper()

    common = [
        "Corsair", "Navigator", "Aviator",
        "Camry", "RAV4", "Highlander",
        "Crosstrek", "Forester", "Outback",
        "Leaf", "Ariya", "Rogue",
        "Mustang Mach-E", "Mach-E", "Edge", "Escape",
        "Ioniq 5", "Kona", "Niro", "EV6", "EV9",
        "ID.4", "Tiguan", "Touareg",
        "Escalade", "Cherokee", "Grand Cherokee",
    ]
    for model in common:
        if model.lower() in clean.lower():
            return model

    return None


def detect_years(text: str):
    return re.findall(r"\b(?:19[8-9]\d|20[0-3]\d)\b", text)


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


def update_memory(memory: dict, text: str):
    memory = dict(memory or {})
    changed = set()

    brand = detect_brand(text)
    if brand and brand != memory.get("brand"):
        memory["brand"] = brand
        changed.add("brand")

    model = detect_model(text, brand or memory.get("brand"))
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


def qualification_reply(memory: dict, changed: set, user_text: str):
    if is_question(user_text):
        return None

    brand = memory.get("brand")
    model = memory.get("model")
    years = memory.get("years")
    mileage = memory.get("mileage")
    trim = memory.get("trim")
    lang = memory.get("language", "uk")
    vehicle = vehicle_label(memory)

    if not changed.intersection({"brand", "model", "years", "drive", "mileage", "trim"}):
        return None

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


def memory_context(memory: dict) -> str:
    fields = []
    for key, label in (
        ("brand", "Марка"),
        ("model", "Модель"),
        ("years", "Рік/роки"),
        ("drive", "Привід"),
        ("mileage", "Пробіг"),
        ("trim", "Комплектація"),
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


async def load_state(db, user_id: int):
    row = await db.prepare(
        "SELECT history_json, memory_json FROM dialog_state WHERE user_id = ?1 LIMIT 1"
    ).bind(user_id).first()

    if not row:
        return [], {}

    try:
        history = json.loads(str(row["history_json"]))
    except Exception:
        history = []

    try:
        memory = json.loads(str(row["memory_json"]))
    except Exception:
        memory = {}

    return trim_history(history), memory


async def save_state(db, user_id: int, chat_id: int, history: list, memory: dict):
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

    await db.prepare(
        """
        INSERT INTO dialog_state (
            user_id, chat_id, history_json, memory_json, state_json, updated_at
        )
        VALUES (?1, ?2, ?3, ?4, '{}', CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            chat_id = excluded.chat_id,
            history_json = excluded.history_json,
            memory_json = excluded.memory_json,
            updated_at = CURRENT_TIMESTAMP
        """
    ).bind(user_id, chat_id, history_json, memory_json).run()


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


async def send_telegram(bot_token: str, chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    response = await fetch(
        url,
        method="POST",
        body=json.dumps({
            "chat_id": chat_id,
            "text": text,
        }, ensure_ascii=False),
        headers={
            "Content-Type": "application/json",
        },
    )

    body = await response.text()

    if response.status != 200:
        raise RuntimeError(
            f"Telegram sendMessage HTTP {response.status}: {body[:500]}"
        )


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

            return Response.json({
                "ok": db_ok and groq_ok and telegram_ok,
                "service": "auction-auto-bot",
                "runtime": "cloudflare-python-worker",
                "d1": db_ok,
                "groq_configured": groq_ok,
                "telegram_configured": telegram_ok,
                "async_webhook": True,
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

            if not chat_id or not user_id:
                return

            chat_id = int(chat_id)
            user_id = int(user_id)
            bot_token = str(self.env.BOT_TOKEN)

            if user_text in ("/start", "/newchat", "/reset"):
                await reset_state(
                    self.env.DB,
                    user_id,
                )

                await send_telegram(
                    bot_token,
                    chat_id,
                    "Вітаю! Я AI-консультант Auction Auto 👋\n"
                    "Допоможу зорієнтуватися по автомобілях із США. "
                    "Який автомобіль Вас цікавить?",
                )
                return

            if not user_text:
                await send_telegram(
                    bot_token,
                    chat_id,
                    "Поки що напишіть запит текстом 🙂",
                )
                return

            history, memory = await load_state(
                self.env.DB,
                user_id,
            )

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

            # Зберігаємо параметри ДО Groq.
            await save_state(
                self.env.DB,
                user_id,
                chat_id,
                history_with_user,
                memory,
            )

            deterministic = qualification_reply(
                memory,
                changed,
                user_text,
            )

            if deterministic:
                answer = deterministic
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
            )

            await send_telegram(
                bot_token,
                chat_id,
                answer,
            )

        except Exception as error:
            print(
                "BACKGROUND PROCESS ERROR:",
                str(error),
            )
