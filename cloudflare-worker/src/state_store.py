import json

from vehicle_logic import new_memory, normalize_memory


def default_state() -> dict:
    return {
        "selection_offered": False,
        "selection_deferred": False,
        "selection_declined": False,
        "waiting_for_phone": False,
        "lead_sent": False,
        "lead_saved": False,
        "admin_send_failed": False,
        "do_not_ask_phone": False,
        "phone": None,
        "ended": False,
    }


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


def _load_json(value, fallback):
    try:
        parsed = json.loads(str(value))
        return parsed
    except Exception:
        return fallback


def trim_history(history: list, limit: int = 14):
    clean = []
    for item in (history or [])[-limit:]:
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            clean.append({
                "role": role,
                "content": content[:2200],
            })
    return clean


async def load_dialog(db, user_id: int):
    row = await db.prepare(
        """
        SELECT history_json, memory_json, state_json
        FROM dialog_state
        WHERE user_id = ?1
        LIMIT 1
        """
    ).bind(user_id).first()

    if not row:
        return [], new_memory(), default_state()

    history = trim_history(_load_json(row["history_json"], []))
    memory = normalize_memory(_load_json(row["memory_json"], {}))

    state = default_state()
    loaded_state = _load_json(row["state_json"], {})
    if isinstance(loaded_state, dict):
        state.update(loaded_state)

    return history, memory, state


async def save_dialog(
    db,
    user_id: int,
    chat_id: int,
    history: list,
    memory: dict,
    state: dict,
):
    await db.prepare(
        """
        INSERT INTO dialog_state (
            user_id,
            chat_id,
            history_json,
            memory_json,
            state_json,
            updated_at
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
        json.dumps(trim_history(history), ensure_ascii=False, separators=(",", ":")),
        json.dumps(normalize_memory(memory), ensure_ascii=False, separators=(",", ":")),
        json.dumps(state, ensure_ascii=False, separators=(",", ":")),
    ).run()


async def reset_dialog(db, user_id: int):
    await db.prepare(
        "DELETE FROM dialog_state WHERE user_id = ?1"
    ).bind(user_id).run()


async def save_lead(
    db,
    user_id: int,
    chat_id: int,
    phone: str,
    summary: str,
):
    await db.prepare(
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
