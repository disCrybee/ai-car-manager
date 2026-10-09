from state_store import save_lead
from telegram_api import send_message
from utils import normalize
from vehicle_logic import normalize_memory


def lead_summary(memory: dict) -> str:
    data = normalize_memory(memory)

    vehicle = " ".join(
        str(x)
        for x in (
            data.get("brand"),
            data.get("model"),
        )
        if x
    ).strip() or "не вказано"

    technical = " / ".join(
        str(x)
        for x in (
            data.get("engine"),
            data.get("battery"),
            data.get("drive"),
        )
        if x
    ).strip() or "не вказано"

    preferences = "; ".join(
        str(x)
        for x in (data.get("preferences") or [])[-6:]
        if x
    ).strip()

    if not preferences:
        preferences = "; ".join(
            str(x)
            for x in (data.get("client_facts") or [])[-6:]
            if x
        ).strip()

    return (
        f"Авто: {vehicle}\n"
        f"Рік: {data.get('year') or 'не вказано'}\n"
        f"Бюджет: {data.get('budget') or 'не вказано'}\n"
        f"Пробіг: {data.get('mileage') or 'не вказано'}\n"
        f"Комплектація: {data.get('trim') or 'не вказано'}\n"
        f"Двигун / батарея / привід: {technical}\n"
        f"Колір: {data.get('color') or 'не вказано'}\n"
        f"Побажання: {preferences or 'не вказано'}"
    )


async def create_and_send_lead(
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
            "saved": True,
            "admin_sent": True,
            "already_sent": True,
        }

    summary = lead_summary(memory)

    if not state.get("lead_saved"):
        await save_lead(
            env.DB,
            user_id,
            chat_id,
            phone,
            summary,
        )
        state["lead_saved"] = True

    state["phone"] = phone
    state["waiting_for_phone"] = False
    state["selection_offered"] = False
    state["selection_deferred"] = False
    state["selection_declined"] = False

    first_name = normalize(sender.get("first_name"))
    last_name = normalize(sender.get("last_name"))
    name = normalize(f"{first_name} {last_name}") or "Без імені"

    username = normalize(sender.get("username"))
    username = f"@{username}" if username else "немає"

    try:
        admin_chat_id = int(normalize(str(env.ADMIN_CHAT_ID)))
    except Exception:
        admin_chat_id = None

    if not admin_chat_id:
        state["admin_send_failed"] = True
        state["lead_sent"] = False
        return {
            "saved": True,
            "admin_sent": False,
            "already_sent": False,
            "error": "ADMIN_CHAT_ID missing",
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
        await send_message(
            str(env.BOT_TOKEN),
            admin_chat_id,
            card,
        )
    except Exception as error:
        state["admin_send_failed"] = True
        state["lead_sent"] = False
        return {
            "saved": True,
            "admin_sent": False,
            "already_sent": False,
            "error": str(error),
        }

    state["admin_send_failed"] = False
    state["lead_sent"] = True

    return {
        "saved": True,
        "admin_sent": True,
        "already_sent": False,
    }


async def admin_check(env):
    try:
        admin_chat_id = int(normalize(str(env.ADMIN_CHAT_ID)))
    except Exception:
        return False, "ADMIN_CHAT_ID не налаштований."

    try:
        await send_message(
            str(env.BOT_TOKEN),
            admin_chat_id,
            "✅ Тест Auction Auto Bot: передача в адмін-групу працює.",
        )
        return True, f"Тестове повідомлення відправлено в ADMIN_CHAT_ID {admin_chat_id}."
    except Exception as error:
        return False, f"Telegram error: {str(error)[:350]}"
