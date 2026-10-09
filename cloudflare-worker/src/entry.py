import json
from urllib.parse import urlparse

from workers import WorkerEntrypoint, Response, fetch


GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
PRIMARY_MODEL = "openai/gpt-oss-120b"
FALLBACK_MODEL = "openai/gpt-oss-20b"

SYSTEM_PROMPT = """
Ти — AI-консультант автомобільної компанії Auction Auto.
Компанія займається підбором, купівлею та доставкою авто з аукціонів США в Україну.

ПРАВИЛА:
- Спілкуйся природно, коротко, зазвичай 1–3 речення.
- Звертайся на "Ви".
- Відповідай мовою поточного повідомлення клієнта: українською або російською.
- Якщо клієнт поставив конкретне питання — спочатку дай відповідь саме на нього.
- Не перетворюй діалог на анкету: став максимум одне логічне уточнення за раз.
- Не проси телефон просто так. Спочатку консультуй.
- Якщо питають, чи ти бот — чесно скажи, що ти AI-консультант Auction Auto.
- Консультуй тільки щодо автомобілів та послуг Auction Auto. Сторонні теми ввічливо відхиляй.

НЕ ВИГАДУЙ:
- актуальну ціну авто на аукціоні;
- конкретні актуальні лоти;
- фінальну вартість авто під ключ;
- доставку, порт, строки, комісії або інші умови компанії, якщо вони не передані системою;
- технічні характеристики, якщо не впевнений.

Перевірені тарифи послуг Auction Auto:
- ціна покупки авто на аукціоні менше $20 000 → послуги $750;
- $20 000–29 999.99 → $1 000;
- $30 000 і більше → $1 500.

"Під ключ" означає фінальну орієнтовну вартість авто вже в Україні.

Для технічних фактів про авто (батарея, двигун, коробка, привід, потужність,
роки випуску, запас ходу, комплектації тощо), якщо тобі доступний Browser Search,
перевір факт через веб перед відповіддю. Віддавай перевагу виробнику, EPA/NHTSA
та надійним автомобільним джерелам. Не називай приблизне значення навмання.

Не вигадуй факт заради красивої відповіді. Якщо даних недостатньо — коротко скажи,
що саме треба уточнити.
""".strip()


TECHNICAL_KEYWORDS = (
    "батар", "квт", "kwh", "ємніст", "емкост", "capacity",
    "двигун", "двигател", "engine", "мотор",
    "короб", "transmission", "cvt", "автомат",
    "потуж", "мощност", "horsepower", "л.с", "к.с",
    "привід", "привод", "awd", "rwd", "fwd", "4wd",
    "запас ходу", "range", "пробег на заряде",
    "розгін", "разгон", "0-100", "0–100", "0-60",
    "комплектац", "trim",
    "роки випуску", "годы выпуска", "model year",
    "рестайл", "facelift",
    "заряд", "charging",
)


def needs_browser_search(text: str) -> bool:
    low = " ".join(text.lower().split())
    return any(keyword in low for keyword in TECHNICAL_KEYWORDS)


def trim_history(history: list, max_messages: int = 12) -> list:
    clean = []
    for item in history[-max_messages:]:
        role = item.get("role")
        content = str(item.get("content", "")).strip()
        if role in ("user", "assistant") and content:
            clean.append({"role": role, "content": content[:2500]})
    return clean


async def ensure_schema(db):
    statements = [
        """
        CREATE TABLE IF NOT EXISTS dialog_state (
            user_id INTEGER PRIMARY KEY,
            chat_id INTEGER NOT NULL,
            history_json TEXT NOT NULL DEFAULT '[]',
            memory_json TEXT NOT NULL DEFAULT '{}',
            state_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS processed_updates (
            update_id INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            phone TEXT,
            summary TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_dialog_updated_at
        ON dialog_state(updated_at)
        """,
    ]
    for sql in statements:
        await db.prepare(sql).run()


async def load_history(db, user_id: int) -> list:
    row = await (
        db.prepare(
            "SELECT history_json FROM dialog_state WHERE user_id = ?1 LIMIT 1"
        )
        .bind(user_id)
        .first()
    )
    if not row:
        return []
    try:
        history = json.loads(str(row["history_json"]))
        if isinstance(history, list):
            return trim_history(history)
    except Exception:
        pass
    return []


async def save_history(db, user_id: int, chat_id: int, history: list):
    payload = json.dumps(
        trim_history(history),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    await (
        db.prepare(
            """
            INSERT INTO dialog_state (
                user_id,
                chat_id,
                history_json,
                memory_json,
                state_json,
                updated_at
            )
            VALUES (?1, ?2, ?3, '{}', '{}', CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                chat_id = excluded.chat_id,
                history_json = excluded.history_json,
                updated_at = CURRENT_TIMESTAMP
            """
        )
        .bind(user_id, chat_id, payload)
        .run()
    )


async def reset_history(db, user_id: int):
    await (
        db.prepare("DELETE FROM dialog_state WHERE user_id = ?1")
        .bind(user_id)
        .run()
    )


async def is_duplicate_update(db, update_id: int) -> bool:
    row = await (
        db.prepare(
            "SELECT update_id FROM processed_updates WHERE update_id = ?1 LIMIT 1"
        )
        .bind(update_id)
        .first()
    )
    return bool(row)


async def mark_update_processed(db, update_id: int):
    await (
        db.prepare(
            """
            INSERT OR IGNORE INTO processed_updates (
                update_id,
                created_at
            )
            VALUES (?1, CURRENT_TIMESTAMP)
            """
        )
        .bind(update_id)
        .run()
    )


async def groq_request(api_key: str, model: str, messages: list, use_browser: bool):
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.15,
        "max_completion_tokens": 350,
        "reasoning_effort": "low",
        "stream": False,
        "citation_options": "disabled",
    }

    if use_browser:
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

    raw = await response.text()

    if response.status != 200:
        raise RuntimeError(
            f"Groq {model} HTTP {response.status}: {raw[:500]}"
        )

    data = json.loads(raw)
    answer = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )

    if not answer:
        raise RuntimeError("Groq повернув порожню відповідь")

    return answer.strip()


async def ask_groq(api_key: str, history: list, user_text: str) -> str:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *trim_history(history),
        {"role": "user", "content": user_text},
    ]

    use_browser = needs_browser_search(user_text)

    try:
        return await groq_request(
            api_key, PRIMARY_MODEL, messages, use_browser
        )
    except Exception as primary_error:
        print("PRIMARY GROQ ERROR:", str(primary_error))
        try:
            return await groq_request(
                api_key, FALLBACK_MODEL, messages, use_browser
            )
        except Exception as fallback_error:
            print("FALLBACK GROQ ERROR:", str(fallback_error))
            raise


def telegram_reply(chat_id: int, text: str):
    return Response.json({
        "method": "sendMessage",
        "chat_id": chat_id,
        "text": text,
    })


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

            return Response.json({
                "ok": db_ok and groq_ok,
                "service": "auction-auto-bot",
                "runtime": "cloudflare-python-worker",
                "d1": db_ok,
                "groq_configured": groq_ok,
            })

        if path != "/telegram-webhook":
            return Response("Auction Auto Worker is running", status=200)

        if request.method != "POST":
            return Response("Method Not Allowed", status=405)

        try:
            update = await request.json()
        except Exception:
            return Response("Bad Request", status=400)

        try:
            await ensure_schema(self.env.DB)
        except Exception as error:
            print("D1 INIT ERROR:", str(error))
            return Response.json({"ok": True})

        update_id = int(update.get("update_id", 0) or 0)

        if update_id:
            try:
                if await is_duplicate_update(self.env.DB, update_id):
                    return Response.json({"ok": True})
            except Exception as error:
                print("DUPLICATE CHECK ERROR:", str(error))

        message = update.get("message")
        if not message:
            if update_id:
                await mark_update_processed(self.env.DB, update_id)
            return Response.json({"ok": True})

        chat = message.get("chat") or {}
        sender = message.get("from") or {}

        chat_id = chat.get("id")
        user_id = sender.get("id") or chat_id
        user_text = (message.get("text") or "").strip()

        if not chat_id or not user_id:
            return Response.json({"ok": True})

        if update_id:
            try:
                await mark_update_processed(self.env.DB, update_id)
            except Exception as error:
                print("MARK UPDATE ERROR:", str(error))

        if user_text in ("/start", "/newchat", "/reset"):
            await reset_history(self.env.DB, int(user_id))
            return telegram_reply(
                int(chat_id),
                "Вітаю! Я AI-консультант Auction Auto 👋\n"
                "Допоможу зорієнтуватися по автомобілях із США. "
                "Який автомобіль Вас цікавить?",
            )

        if not user_text:
            return telegram_reply(
                int(chat_id),
                "Поки що найкраще напишіть запит текстом 🙂",
            )

        try:
            history = await load_history(self.env.DB, int(user_id))
            api_key = str(self.env.GROQ_API_KEY)

            answer = await ask_groq(api_key, history, user_text)

            new_history = [
                *history,
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": answer},
            ]

            await save_history(
                self.env.DB,
                int(user_id),
                int(chat_id),
                new_history,
            )

            return telegram_reply(int(chat_id), answer)

        except Exception as error:
            print("MESSAGE PROCESSING ERROR:", str(error))
            return telegram_reply(
                int(chat_id),
                "Зараз AI тимчасово не зміг обробити запит. "
                "Спробуйте, будь ласка, ще раз трохи пізніше.",
            )
