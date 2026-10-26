"""One-time phone completion for the single controlled HelpCrunch pilot.

A completed pilot chat stays silent. Never store or print the phone number
here; HelpCrunch already contains the client's message.
"""
import re

PHONE = re.compile(r"(?<!\d)(?:\+\d[\d\s()\-]{8,20}\d|0\d[\d\s()\-]{7,18}\d)(?!\d)")
DONE_APPLICATION = -2
DONE_CHAT = 60354
ACK = "Дякую! Ваш номер отримав. Менеджер зв'яжеться з Вами найближчим часом."


def contains_phone(text):
    if not isinstance(text, str):
        return False
    for match in PHONE.finditer(text):
        digits = re.sub(r"\D", "", match.group())
        if 9 <= len(digits) <= 15:
            return True
    return False


async def pilot_is_done(db):
    row = await db.prepare(
        "SELECT state_json FROM hc_dialog_state WHERE chat_id = ? AND application_id = ?"
    ).bind(DONE_CHAT, DONE_APPLICATION).first()
    return bool(row)


async def pilot_mark_done(db):
    # Reserve completion before the network send. Fails closed if sending fails.
    await db.prepare(
        "INSERT OR IGNORE INTO hc_dialog_state(chat_id, application_id, state_json) "
        "VALUES (?, ?, ?)"
    ).bind(DONE_CHAT, DONE_APPLICATION, '{"completed":true}').run()

# A completed lead can start a new request when a concrete new vehicle is named.
# Short thanks or waiting acknowledgements must remain silent.
NEW_REQUEST = re.compile(
    r"(?i)\b(?:tesla|bmw|audi|volkswagen|vw|mercedes|toyota|honda|"
    r"skoda|porsche|ford|hyundai|kia|lexus|mazda|nissan|volvo|"
    r"renault|peugeot|citroen|land rover|range rover)\b"
)

def is_new_vehicle_request(text):
    if not isinstance(text, str):
        return False
    return bool(NEW_REQUEST.search(text.strip())) and not contains_phone(text)


async def pilot_clear_done(db):
    await db.prepare(
        "DELETE FROM hc_dialog_state WHERE chat_id = ? AND application_id = ?"
    ).bind(DONE_CHAT, DONE_APPLICATION).run()

QUESTION_WORDS = ("скільки", "доставка", "кошту", "вартіст", "ціна", "термін", "строк", "коли", "як ", "чи ", "де ")

def is_substantive_followup(text):
    if not isinstance(text, str):
        return False
    value = text.strip().casefold()
    return bool(value and (is_new_vehicle_request(value) or
           ("?" in value and len(value) >= 12) or
           any(word in value for word in QUESTION_WORDS)) and not contains_phone(value))
