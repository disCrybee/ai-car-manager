import json

from workers import fetch


async def send_message(
    bot_token: str,
    chat_id: int,
    text: str,
    reply_markup=None,
):
    payload = {
        "chat_id": chat_id,
        "text": text,
    }

    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    response = await fetch(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        method="POST",
        headers={"Content-Type": "application/json"},
        body=json.dumps(payload, ensure_ascii=False),
    )

    body = await response.text()

    if response.status != 200:
        raise RuntimeError(
            f"Telegram sendMessage HTTP {response.status}: {body[:500]}"
        )

    try:
        result = json.loads(body)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("Telegram returned invalid JSON") from exc

    if not result.get("ok"):
        raise RuntimeError(
            f"Telegram sendMessage failed: {result.get('description', body[:350])}"
        )

    return result


def main_keyboard():
    return {
        "keyboard": [
            [{"text": "👨‍💼 Виклик менеджера"}],
            [
                {"text": "🔄 Почати новий чат"},
                {"text": "✅ Завершити чат"},
            ],
        ],
        "resize_keyboard": True,
        "input_field_placeholder": "Напишіть повідомлення...",
    }


def selection_keyboard():
    return {
        "keyboard": [
            [
                {"text": "✅ Так, підібрати"},
                {"text": "❌ Ні, дякую"},
            ],
            [{"text": "👨‍💼 Виклик менеджера"}],
            [
                {"text": "🔄 Почати новий чат"},
                {"text": "✅ Завершити чат"},
            ],
        ],
        "resize_keyboard": True,
        "input_field_placeholder": "Напишіть повідомлення...",
    }


def phone_keyboard():
    return {
        "keyboard": [
            [
                {
                    "text": "📱 Поділитися номером",
                    "request_contact": True,
                }
            ],
            [{"text": "👨‍💼 Виклик менеджера"}],
            [
                {"text": "🔄 Почати новий чат"},
                {"text": "✅ Завершити чат"},
            ],
        ],
        "resize_keyboard": True,
        "input_field_placeholder": "Надішліть номер або продовжуйте діалог...",
    }
