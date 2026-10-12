from urllib.parse import urlparse

from workers import WorkerEntrypoint, Response

from ai_engine import classify_body_type, consult, extract_slots
from lead_flow import admin_check, create_and_send_lead
from pricing import (
    answer_logistics,
    is_logistics_question,
    is_service_fee_question,
    is_turnkey_price_question,
    service_fee_answer,
    turnkey_price_answer,
)
from state_store import ensure_schema, load_dialog, reset_dialog, save_dialog
from telegram_api import (
    main_keyboard,
    phone_keyboard,
    selection_keyboard,
    send_message,
)
from utils import (
    clean_phone,
    is_affirmative,
    is_negative,
    is_simple_ack,
    looks_like_phone,
    normalize,
)
from vehicle_logic import (
    explicit_selection_intent,
    extract_deterministic,
    is_question,
    merge_ai_slots,
    missing_required,
    next_question,
    no_phone_request,
    normalize_memory,
    phone_request,
    qualification_ready,
    selection_offer,
    should_try_ai_extractor,
)


VERSION = "cloud-refactor-2026-10-09-v1"


def _append_history(history: list, role: str, content: str):
    result = list(history or [])
    if content:
        result.append({
            "role": role,
            "content": content,
        })
    return result[-14:]


async def _persist_and_send(
    env,
    user_id: int,
    chat_id: int,
    history: list,
    memory: dict,
    state: dict,
    answer: str,
    *,
    keyboard=None,
):
    history = _append_history(
        history,
        "assistant",
        answer,
    )

    await save_dialog(
        env.DB,
        user_id,
        chat_id,
        history,
        memory,
        state,
    )

    await send_message(
        str(env.BOT_TOKEN),
        chat_id,
        answer,
        reply_markup=keyboard or main_keyboard(),
    )


async def _request_phone(
    env,
    user_id: int,
    chat_id: int,
    history: list,
    memory: dict,
    state: dict,
):
    if state.get("lead_sent"):
        await _persist_and_send(
            env,
            user_id,
            chat_id,
            history,
            memory,
            state,
            (
                "Ваш контакт уже передано менеджеру 👍 Можемо продовжити консультацію."
                if memory.get("language") == "uk"
                else
                "Ваш контакт уже передан менеджеру 👍 Можем продолжить консультацию."
            ),
            keyboard=main_keyboard(),
        )
        return

    if state.get("do_not_ask_phone"):
        await _persist_and_send(
            env,
            user_id,
            chat_id,
            history,
            memory,
            state,
            (
                "Добре, номер просити не буду. Можемо продовжити консультацію тут."
                if memory.get("language") == "uk"
                else
                "Хорошо, номер просить не буду. Можем продолжить консультацию здесь."
            ),
            keyboard=main_keyboard(),
        )
        return

    state["waiting_for_phone"] = True
    state["selection_offered"] = False
    state["selection_deferred"] = False

    await _persist_and_send(
        env,
        user_id,
        chat_id,
        history,
        memory,
        state,
        phone_request(memory),
        keyboard=phone_keyboard(),
    )


async def _handle_lead_contact(
    env,
    sender: dict,
    user_id: int,
    chat_id: int,
    history: list,
    memory: dict,
    state: dict,
    phone: str,
):
    result = await create_and_send_lead(
        env,
        sender,
        user_id,
        chat_id,
        phone,
        memory,
        state,
    )

    if result.get("admin_sent"):
        answer = (
            "Дякую 👍 Контакт передано менеджеру. Він перегляне актуальні варіанти та зв'яжеться з Вами."
            if memory.get("language") == "uk"
            else
            "Спасибо 👍 Контакт передан менеджеру. Он посмотрит актуальные варианты и свяжется с Вами."
        )
    else:
        print("LEAD ADMIN DELIVERY ERROR:", result.get("error"))
        answer = (
            "Дякую 👍 Контакт збережено. Передача менеджеру зараз затрималась, але Ваш лід не втрачено."
            if memory.get("language") == "uk"
            else
            "Спасибо 👍 Контакт сохранён. Передача менеджеру сейчас задержалась, но Ваш лид не потерян."
        )

    await _persist_and_send(
        env,
        user_id,
        chat_id,
        history,
        memory,
        state,
        answer,
        keyboard=main_keyboard(),
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

            def configured(name: str):
                try:
                    return bool(normalize(str(getattr(self.env, name))))
                except Exception:
                    return False

            return Response.json({
                "ok": (
                    db_ok
                    and configured("BOT_TOKEN")
                    and configured("GROQ_API_KEY")
                ),
                "service": "auction-auto-bot",
                "version": VERSION,
                "runtime": "cloudflare-python-worker",
                "d1": db_ok,
                "telegram_configured": configured("BOT_TOKEN"),
                "groq_configured": configured("GROQ_API_KEY"),
                "admin_configured": configured("ADMIN_CHAT_ID"),
                "required_qualification": [
                    "brand",
                    "model",
                    "year",
                    "mileage",
                    "trim",
                ],
                "verified_logistics": True,
                "lead_flow": True,
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

        # Telegram receives ACK immediately; processing continues in background.
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

            if not chat_id or not user_id:
                return

            chat_id = int(chat_id)
            user_id = int(user_id)

            bot_token = str(self.env.BOT_TOKEN)
            text = normalize(message.get("text"))
            contact = message.get("contact") or {}

            # Diagnostics.
            if text == "/chatid":
                await send_message(
                    bot_token,
                    chat_id,
                    f"Chat ID:\n{chat_id}",
                )
                return

            if text == "/admincheck":
                ok, details = await admin_check(self.env)
                await send_message(
                    bot_token,
                    chat_id,
                    ("✅ " if ok else "❌ ") + details,
                )
                return

            # New conversation.
            if text in (
                "/start",
                "/newchat",
                "/reset",
                "🔄 Почати новий чат",
            ):
                await reset_dialog(
                    self.env.DB,
                    user_id,
                )

                answer = (
                    "Добре 👍 Починаємо новий діалог. Напишіть, яке авто Вас цікавить."
                    if text == "🔄 Почати новий чат"
                    else
                    "Добрий день! 👋 Напишіть, яке авто Вас цікавить — допоможу зорієнтуватися."
                )

                await send_message(
                    bot_token,
                    chat_id,
                    answer,
                    reply_markup=main_keyboard(),
                )
                return

            history, memory, state = await load_dialog(
                self.env.DB,
                user_id,
            )
            memory = normalize_memory(memory)

            # End chat.
            if text == "✅ Завершити чат":
                state["ended"] = True
                await _persist_and_send(
                    self.env,
                    user_id,
                    chat_id,
                    history,
                    memory,
                    state,
                    "Чат завершено. Щоб почати знову, натисніть «🔄 Почати новий чат».",
                    keyboard=main_keyboard(),
                )
                return

            if state.get("ended"):
                await send_message(
                    bot_token,
                    chat_id,
                    "Цей діалог завершено. Натисніть «🔄 Почати новий чат», щоб продовжити.",
                    reply_markup=main_keyboard(),
                )
                return

            # Contact object from Telegram request_contact button.
            phone = normalize(contact.get("phone_number"))
            if phone:
                await _handle_lead_contact(
                    self.env,
                    sender,
                    user_id,
                    chat_id,
                    history,
                    memory,
                    state,
                    phone,
                )
                return

            if not text:
                await send_message(
                    bot_token,
                    chat_id,
                    "Напишіть запит текстом або скористайтеся кнопками нижче.",
                    reply_markup=(
                        phone_keyboard()
                        if state.get("waiting_for_phone")
                        else main_keyboard()
                    ),
                )
                return

            if no_phone_request(text):
                state["do_not_ask_phone"] = True
                state["waiting_for_phone"] = False

            # Manager button = explicit next step.
            if text == "👨‍💼 Виклик менеджера":
                await _request_phone(
                    self.env,
                    user_id,
                    chat_id,
                    history,
                    memory,
                    state,
                )
                return

            if text == "📱 Поділитися номером":
                state["waiting_for_phone"] = True
                await _persist_and_send(
                    self.env,
                    user_id,
                    chat_id,
                    history,
                    memory,
                    state,
                    phone_request(memory),
                    keyboard=phone_keyboard(),
                )
                return

            # Retry a previously saved lead without asking for the phone again.
            # A Telegram API outage or missing group permissions must not lose the lead.
            if state.get("lead_saved") and not state.get("lead_sent") and state.get("phone"):
                await _handle_lead_contact(
                    self.env,
                    sender,
                    user_id,
                    chat_id,
                    history,
                    memory,
                    state,
                    state["phone"],
                )
                return

            # Manual phone number.
            if state.get("waiting_for_phone") and looks_like_phone(text):
                await _handle_lead_contact(
                    self.env,
                    sender,
                    user_id,
                    chat_id,
                    history,
                    memory,
                    state,
                    clean_phone(text),
                )
                return

            # Answer to the selection offer.
            if state.get("selection_offered"):
                if is_affirmative(text):
                    await _request_phone(
                        self.env,
                        user_id,
                        chat_id,
                        history,
                        memory,
                        state,
                    )
                    return

                if is_negative(text):
                    state["selection_offered"] = False
                    state["selection_declined"] = True

                    await _persist_and_send(
                        self.env,
                        user_id,
                        chat_id,
                        history,
                        memory,
                        state,
                        (
                            "Добре 👍 Тоді продовжимо консультацію без підбору."
                            if memory.get("language") == "uk"
                            else
                            "Хорошо 👍 Тогда продолжим консультацию без подбора."
                        ),
                        keyboard=main_keyboard(),
                    )
                    return

                # Client asked another question instead of yes/no.
                if is_question(text) or is_logistics_question(text):
                    state["selection_offered"] = False
                    state["selection_deferred"] = True

            # Deferred offer: a later clear yes should still mean "show variants".
            if state.get("selection_deferred"):
                if is_affirmative(text):
                    await _request_phone(
                        self.env,
                        user_id,
                        chat_id,
                        history,
                        memory,
                        state,
                    )
                    return

                if is_negative(text):
                    state["selection_deferred"] = False
                    state["selection_declined"] = True

                    await _persist_and_send(
                        self.env,
                        user_id,
                        chat_id,
                        history,
                        memory,
                        state,
                        (
                            "Добре 👍 Продовжимо консультацію."
                            if memory.get("language") == "uk"
                            else
                            "Хорошо 👍 Продолжим консультацию."
                        ),
                    )
                    return

            # Explicit order/pick request at any point.
            if explicit_selection_intent(text):
                await _request_phone(
                    self.env,
                    user_id,
                    chat_id,
                    history,
                    memory,
                    state,
                )
                return

            # Deterministic extraction first.
            memory, changed = extract_deterministic(
                memory,
                text,
            )

            # Fallback semantic extraction makes the flow brand/model agnostic.
            if should_try_ai_extractor(memory, text, changed):
                slots = await extract_slots(
                    str(self.env.GROQ_API_KEY),
                    memory,
                    text,
                )
                memory, ai_changed = merge_ai_slots(
                    memory,
                    slots,
                )
                changed |= ai_changed

            # A missing mileage unit is an unresolved answer, not a consultation.
            # Never advance to trim or send AI technical commentary until resolved.
            if memory.get("mileage_pending") and not memory.get("mileage"):
                topic, question = next_question(memory)
                memory["last_question_topic"] = topic
                await _persist_and_send(
                    self.env, user_id, chat_id, history, memory, state, question,
                )
                return

            history = _append_history(
                history,
                "user",
                text,
            )

            # Save client facts before any external API call.
            await save_dialog(
                self.env.DB,
                user_id,
                chat_id,
                history,
                memory,
                state,
            )

            # Company service fee: deterministic.
            if is_service_fee_question(text):
                answer = service_fee_answer(
                    text,
                    memory,
                )

                await _persist_and_send(
                    self.env,
                    user_id,
                    chat_id,
                    history,
                    memory,
                    state,
                    answer,
                )
                return

            # Verified Auction Auto logistics only.
            if is_logistics_question(text):
                answer, memory, needs_category = answer_logistics(
                    text,
                    memory,
                )

                if needs_category and memory.get("brand") and memory.get("model"):
                    category = await classify_body_type(
                        str(self.env.GROQ_API_KEY),
                        memory,
                    )

                    if category:
                        answer, memory, _ = answer_logistics(
                            text,
                            memory,
                            body_category=category,
                        )

                if qualification_ready(memory) and not state.get("lead_sent"):
                    state["selection_deferred"] = True
                    state["selection_offered"] = False

                await _persist_and_send(
                    self.env,
                    user_id,
                    chat_id,
                    history,
                    memory,
                    state,
                    answer,
                )
                return

            # "How much turnkey?" never gets an invented market price.
            if is_turnkey_price_question(text):
                answer, topic = turnkey_price_answer(
                    memory,
                )

                if topic:
                    memory["last_question_topic"] = topic

                elif qualification_ready(memory) and not state.get("lead_sent"):
                    if not state.get("selection_declined"):
                        state["selection_offered"] = True
                        answer = answer + "\n\n" + selection_offer(memory)

                await _persist_and_send(
                    self.env,
                    user_id,
                    chat_id,
                    history,
                    memory,
                    state,
                    answer,
                    keyboard=(
                        selection_keyboard()
                        if state.get("selection_offered")
                        else main_keyboard()
                    ),
                )
                return

            # If consultation interrupted an earlier offer, "зрозуміло/понятно"
            # naturally returns to the offer, like the reference dialogue.
            if (
                state.get("selection_deferred")
                and is_simple_ack(text)
                and qualification_ready(memory)
                and not state.get("lead_sent")
                and not state.get("selection_declined")
            ):
                state["selection_deferred"] = False
                state["selection_offered"] = True

                await _persist_and_send(
                    self.env,
                    user_id,
                    chat_id,
                    history,
                    memory,
                    state,
                    selection_offer(memory),
                    keyboard=selection_keyboard(),
                )
                return

            # Explicit vehicle question -> consultation. Never trigger AI from a bare
            # answer like "2015-2017", "до 200000 км", "Максимальна".
            if is_question(text):
                try:
                    answer = await consult(
                        str(self.env.GROQ_API_KEY),
                        history[:-1],
                        memory,
                        text,
                    )
                except Exception as error:
                    print("CONSULTATION ERROR:", str(error))
                    answer = (
                        "Не хочу давати неточну інформацію: зараз не вдалося надійно перевірити цей факт. "
                        "Можете повторити питання трохи пізніше."
                        if memory.get("language") == "uk"
                        else
                        "Не хочу давать неточную информацию: сейчас не удалось надёжно проверить этот факт. "
                        "Можете повторить вопрос немного позже."
                    )

                # Continue qualification with only one logical question.
                if not qualification_ready(memory):
                    topic, question = next_question(memory)
                    if question:
                        memory["last_question_topic"] = topic
                        answer = answer + "\n\n" + question

                elif (
                    not state.get("lead_sent")
                    and not state.get("selection_declined")
                    and not state.get("selection_offered")
                    and not state.get("selection_deferred")
                ):
                    state["selection_offered"] = True
                    answer = answer + "\n\n" + selection_offer(memory)

                await _persist_and_send(
                    self.env,
                    user_id,
                    chat_id,
                    history,
                    memory,
                    state,
                    answer,
                    keyboard=(
                        selection_keyboard()
                        if state.get("selection_offered")
                        else main_keyboard()
                    ),
                )
                return

            # Pure qualification: Brand -> Model -> Year -> Mileage -> Trim.
            topic, question = next_question(memory)

            if question:
                memory["last_question_topic"] = topic

                await _persist_and_send(
                    self.env,
                    user_id,
                    chat_id,
                    history,
                    memory,
                    state,
                    question,
                    keyboard=main_keyboard(),
                )
                return

            # Exactly after all five required preferences are known.
            if (
                qualification_ready(memory)
                and not state.get("lead_sent")
                and not state.get("selection_declined")
            ):
                state["selection_offered"] = True
                state["selection_deferred"] = False
                memory["last_question_topic"] = None

                await _persist_and_send(
                    self.env,
                    user_id,
                    chat_id,
                    history,
                    memory,
                    state,
                    selection_offer(memory),
                    keyboard=selection_keyboard(),
                )
                return

            # Post-lead conversation remains available indefinitely.
            await _persist_and_send(
                self.env,
                user_id,
                chat_id,
                history,
                memory,
                state,
                (
                    "Добре. Ставте питання по авто — підкажу."
                    if memory.get("language") == "uk"
                    else
                    "Хорошо. Задавайте вопросы по авто — подскажу."
                ),
                keyboard=main_keyboard(),
            )

        except Exception as error:
            # Telegram already got HTTP 200, so make the error observable.
            print("BACKGROUND PROCESS ERROR:", str(error))
