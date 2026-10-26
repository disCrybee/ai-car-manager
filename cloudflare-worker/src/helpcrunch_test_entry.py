"""Isolated HelpCrunch receiver for safe staging; never sends chat replies."""
from workers import WorkerEntrypoint, Response
from urllib.parse import urlparse
import hmac
import json
from helpcrunch_groq import generate_reply
from helpcrunch_shipping_lookup import shipping_context, confirmed_route_reply
from helpcrunch_budget_guard import fresh_consultation, low_usd_budget_reply
from helpcrunch_api import list_agents, manager_candidates, get_chat_messages, send_test_message
from helpcrunch_demo_memory import load_demo_history, save_demo_history, demo_chat_id, DEMO_APPLICATION
from helpcrunch_webhook import describe_event, verify_signature
from helpcrunch_brands import configured_brands, brand_for_application
from helpcrunch_planner import plan_incoming
from helpcrunch_test_dispatch import enabled_for_event, reserve_test_reply
from helpcrunch_pilot_completion import contains_phone, pilot_is_done, pilot_mark_done, pilot_clear_done, is_new_vehicle_request, is_substantive_followup, ACK
from helpcrunch_preview_pipeline import process_preview


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        path = urlparse(request.url).path
        if path == "/health":
            db = getattr(self.env, "HC_DB", None)
            readable = False
            if db is not None:
                try:
                    await db.prepare("SELECT COUNT(*) AS n FROM hc_dialog_state").first()
                    await db.prepare("SELECT COUNT(*) AS n FROM hc_processed_events").first()
                    readable = True
                except Exception:
                    print("HelpCrunch staging D1 health check failed")
            return Response.json({
                "ok": True, "service": "helpcrunch-test", "mode": "receive-only",
                "memory_configured": db is not None,
                "memory_readable": readable, "outbound_enabled": False,
                "demo_token_configured": bool(str(getattr(self.env, "HELPCRUNCH_DEMO_TOKEN", "") or "")),
                "groq_key_configured": bool(str(getattr(self.env, "GROQ_API_KEY", "") or "")),
                "pilot_enabled": str(getattr(self.env, "HELPCRUNCH_PILOT_ENABLED", "") or "").strip().lower() == "true",
                "pilot_binding_present": getattr(self.env, "HELPCRUNCH_PILOT_ENABLED", None) is not None,
                "pilot_binding_type": type(getattr(self.env, "HELPCRUNCH_PILOT_ENABLED", None)).__name__
            })
        if path == "/demo-helpcrunch-agents":
            if request.method != "GET":
                return Response("Method Not Allowed", status=405)
            token = str(getattr(self.env, "HELPCRUNCH_DEMO_TOKEN", "") or "")
            supplied = request.headers.get("Authorization", "")
            if not token or not hmac.compare_digest(supplied, "Bearer " + token):
                return Response("Unauthorized", status=401)
            api_key = str(getattr(self.env, "HELPCRUNCH_API_KEY", "") or "")
            if not api_key:
                return Response.json({"ok": False, "error": "HelpCrunch API not configured"}, status=503)
            try:
                candidates = manager_candidates(await list_agents(api_key))
                return Response.json({"ok": True, "candidates": candidates,
                                      "outbound_enabled": False})
            except Exception as exc:
                print("HelpCrunch agent lookup failure", type(exc).__name__)
                return Response.json({"ok": False, "error": "Agent lookup failed"}, status=502)
        if path == "/demo-helpcrunch-chat-check":
            if request.method != "GET":
                return Response("Method Not Allowed", status=405)
            token = str(getattr(self.env, "HELPCRUNCH_DEMO_TOKEN", "") or "")
            if not token or not hmac.compare_digest(
                request.headers.get("Authorization", ""), "Bearer " + token
            ):
                return Response("Unauthorized", status=401)
            api_key = str(getattr(self.env, "HELPCRUNCH_API_KEY", "") or "")
            if not api_key:
                return Response.json({"ok": False, "error": "HelpCrunch API not configured"}, status=503)
            try:
                # Fixed approved test chat; never accept an arbitrary user-supplied ID.
                data = await get_chat_messages(api_key, 60354)
                if not isinstance(data, (dict, list)):
                    raise ValueError("Unexpected HelpCrunch response")
                return Response.json({
                    "ok": True, "chat_id": 60354, "agent_id": 21,
                    "read_access": True, "outbound_enabled": False,
                })
            except Exception as exc:
                print("HelpCrunch test chat read failed", type(exc).__name__)
                return Response.json({"ok": False, "error": "Chat read failed"}, status=502)
        if path == "/demo-helpcrunch-send":
            if request.method != "POST":
                return Response("Method Not Allowed", status=405)
            token = str(getattr(self.env, "HELPCRUNCH_DEMO_TOKEN", "") or "")
            if not token or not hmac.compare_digest(
                request.headers.get("Authorization", ""), "Bearer " + token
            ):
                return Response("Unauthorized", status=401)
            api_key = str(getattr(self.env, "HELPCRUNCH_API_KEY", "") or "")
            if not api_key:
                return Response.json({"ok": False, "error": "HelpCrunch API not configured"}, status=503)
            # Exactly one designated chat and agent. No caller-controlled message body.
            # Sending requires an authenticated POST from the operator.
            try:
                result = await send_test_message(
                    api_key, 60354, 21,
                    "Тестове повідомлення AI-менеджера. Перевіряємо доставку через HelpCrunch.",
                    allowed_chat_id=60354, allowed_agent_id=21, enabled=True,
                )
                message_id = result.get("id") if isinstance(result, dict) else None
                return Response.json({
                    "ok": True, "chat_id": 60354, "agent_id": 21,
                    "message_id": message_id, "test_only": True,
                })
            except Exception as exc:
                print("HelpCrunch restricted test send failed", type(exc).__name__)
                return Response.json({"ok": False, "error": "Test send failed"}, status=502)
        if path == "/demo-helpcrunch-reset":
            if request.method != "POST":
                return Response("Method Not Allowed", status=405)
            token = str(getattr(self.env, "HELPCRUNCH_DEMO_TOKEN", "") or "")
            if not token or not hmac.compare_digest(
                request.headers.get("Authorization", ""), "Bearer " + token
            ):
                return Response("Unauthorized", status=401)
            db = getattr(self.env, "HC_DB", None)
            if db is None:
                return Response.json({"ok": False, "error": "D1 not configured"}, status=503)
            try:
                # Remove only controlled pilot state; never touch chat messages or other users.
                await db.prepare(
                    "DELETE FROM hc_dialog_state WHERE chat_id = ? AND application_id = ?"
                ).bind(60354, -2).run()
                await db.prepare(
                    "DELETE FROM hc_dialog_state WHERE chat_id = ? AND application_id = ?"
                ).bind(demo_chat_id("hc60354-webhook", token), DEMO_APPLICATION).run()
                return Response.json({"ok": True, "pilot_chat": 60354,
                                      "memory_reset": True, "outbound_enabled_globally": False})
            except Exception as exc:
                print("Pilot reset failed", type(exc).__name__)
                return Response.json({"ok": False, "error": "Reset failed"}, status=502)
        if path == "/demo-helpcrunch-ai-send":
            if request.method != "POST":
                return Response("Method Not Allowed", status=405)
            token = str(getattr(self.env, "HELPCRUNCH_DEMO_TOKEN", "") or "")
            if not token or not hmac.compare_digest(
                request.headers.get("Authorization", ""), "Bearer " + token
            ):
                return Response("Unauthorized", status=401)
            groq_key = str(getattr(self.env, "GROQ_API_KEY", "") or "")
            hc_key = str(getattr(self.env, "HELPCRUNCH_API_KEY", "") or "")
            db = getattr(self.env, "HC_DB", None)
            if not groq_key or not hc_key or db is None:
                return Response.json({"ok": False, "error": "Missing test configuration"}, status=503)
            stage = "input"
            try:
                raw_body = await request.text()
                if len(raw_body) > 4000:
                    return Response("Request Too Large", status=413)
                data = json.loads(raw_body)
                if not isinstance(data, dict):
                    raise ValueError("Bad request")
                prompt = data.get("text")
                if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 1000:
                    raise ValueError("Invalid prompt")
                # A fixed internal session and explicit test-only chat/agent.
                session = "hc60354-ai-test"
                stage = "memory_read"
                history = await load_demo_history(db, session, token)
                turns = history + [{"role": "user", "content": prompt}]
                stage = "groq"
                answer = confirmed_route_reply(turns)
                if answer is None:
                    answer = await generate_reply(groq_key, "Auction Auto", turns,
                                                  company_context=shipping_context(turns))
                stage = "helpcrunch_send"
                await send_test_message(
                    hc_key, 60354, 21, answer,
                    allowed_chat_id=60354, allowed_agent_id=21, enabled=True,
                )
                stage = "memory_write"
                await save_demo_history(db, session, token, turns + [
                    {"role": "assistant", "content": answer}
                ])
                return Response.json({
                    "ok": True, "chat_id": 60354, "agent_id": 21,
                    "mode": "manual-ai-test", "outbound_enabled_globally": False,
                })
            except (ValueError, TypeError):
                return Response("Bad Request", status=400)
            except Exception as exc:
                print("HelpCrunch controlled AI-send failed", stage, type(exc).__name__)
                return Response.json({
                    "ok": False, "error": "AI test failed", "stage": stage,
                }, status=502)
        if path == "/demo-groq":
            if request.method != "POST":
                return Response("Method Not Allowed", status=405)
            token = str(getattr(self.env, "HELPCRUNCH_DEMO_TOKEN", "") or "")
            supplied = request.headers.get("Authorization", "")
            if not token or not hmac.compare_digest(supplied, "Bearer " + token):
                return Response.json({
                    "ok": False, "error": "Unauthorized",
                    "authorization_present": bool(supplied),
                    "bearer_scheme": supplied.startswith("Bearer "),
                }, status=401)
            api_key = str(getattr(self.env, "GROQ_API_KEY", "") or "")
            if not api_key:
                return Response.json({"ok": False, "error": "Groq secret is not configured"}, status=503)
            stage = "input"
            try:
                raw_demo = await request.text()
                if len(raw_demo) > 6000:
                    return Response("Request Too Large", status=413)
                incoming = json.loads(raw_demo)
                if not isinstance(incoming, dict):
                    raise ValueError("Invalid body")
                user_text = incoming.get("text")
                if not isinstance(user_text, str) or not 1 <= len(user_text.strip()) <= 1000:
                    raise ValueError("Invalid text")
                session = incoming.get("session")
                db = getattr(self.env, "HC_DB", None)
                if session is not None and db is None:
                    return Response.json({"ok": False, "error": "Demo memory unavailable"}, status=503)
                stage = "memory_read"
                history = await load_demo_history(db, session, token) if session is not None else []
                messages = history + [{"role": "user", "content": user_text}]
                stage = "groq"
                reply = await generate_reply(api_key, None, messages)
                if session is not None:
                    stage = "memory_write"
                    await save_demo_history(db, session, token, messages + [
                        {"role": "assistant", "content": reply}
                    ])
                return Response.json({"ok": True, "reply": reply, "mode": "isolated-demo",
                                      "memory_enabled": session is not None})
            except (ValueError, TypeError):
                return Response("Bad Request", status=400)
            except Exception as exc:
                print("HelpCrunch isolated demo stage failed:", stage, type(exc).__name__)
                return Response.json({"ok": False, "error": "Generation failed", "stage": stage,
                                      "error_type": type(exc).__name__}, status=502)
        if path != "/helpcrunch-webhook":
            return Response("Not Found", status=404)
        if request.method != "POST":
            return Response("Method Not Allowed", status=405)
        secret = str(getattr(self.env, "HELPCRUNCH_WEBHOOK_SIGNING_KEY", "") or "")
        if not secret:
            return Response("Not Configured", status=503)
        raw = (await request.text()).encode("utf-8")
        if not verify_signature(raw, secret, request.headers.get("X-HelpCrunch-Signature", "")):
            return Response("Unauthorized", status=401)
        try:
            plan = plan_incoming(raw)
            metadata = plan["metadata"]
            # Pilot is off unless deliberately enabled via Worker secret/variable.
            pilot_flag = str(getattr(self.env, "HELPCRUNCH_PILOT_ENABLED", "") or "")
            if pilot_flag == "true" and str(metadata.get("chat_id")) != "60354":
                # Ignore all other chats without storing their data.
                return Response.json({"ok": True, "mode": "pilot-other-chat-ignored"})
            if enabled_for_event(metadata, pilot_flag):
                db = getattr(self.env, "HC_DB", None)
                groq_key = str(getattr(self.env, "GROQ_API_KEY", "") or "")
                hc_key = str(getattr(self.env, "HELPCRUNCH_API_KEY", "") or "")
                memory_secret = str(getattr(self.env, "HELPCRUNCH_DEMO_TOKEN", "") or "")
                if db is None or not groq_key or not hc_key or not memory_secret:
                    return Response.json({"ok": False, "error": "Pilot not configured"}, status=503)
                payload = json.loads(raw)
                incoming = payload["eventData"]["message"]["text"]
                completed = await pilot_is_done(db)
                restarting = fresh_consultation(incoming) or (completed and is_new_vehicle_request(incoming))
                followup = completed and is_substantive_followup(incoming)
                if completed and not followup:
                    return Response.json({"ok": True, "mode": "pilot-completed-silent"})
                # Reserve before non-idempotent send, including a restarted conversation.
                if not await reserve_test_reply(db, metadata):
                    return Response.json({"ok": True, "mode": "pilot-duplicate"})
                if restarting:
                    await pilot_clear_done(db)
                if not isinstance(incoming, str) or not 1 <= len(incoming.strip()) <= 1000:
                    return Response.json({"ok": True, "mode": "pilot-ignored"})
                session = "hc60354-webhook"
                try:
                    history = [] if restarting else await load_demo_history(db, session, memory_secret)
                    turns = history + [{"role": "user", "content": incoming}]
                    if contains_phone(incoming) and not completed:
                        await pilot_mark_done(db)
                        answer = ACK
                    else:
                        answer = low_usd_budget_reply(incoming) if restarting else None
                        if answer is None:
                            answer = confirmed_route_reply(turns)
                        if answer is None:
                            answer = await generate_reply(groq_key, "Auction Auto", turns,
                                                          company_context=shipping_context(turns))
                    await send_test_message(
                        hc_key, 60354, 21, answer,
                        allowed_chat_id=60354, allowed_agent_id=21, enabled=True,
                    )
                    await save_demo_history(db, session, memory_secret, turns + [
                        {"role": "assistant", "content": answer}
                    ])
                    return Response.json({"ok": True, "mode": "pilot-replied"})
                except Exception as exc:
                    # An uncertain send must never be repeated automatically.
                    print("HelpCrunch pilot failed; event reserved", type(exc).__name__)
                    return Response.json({"ok": False, "error": "Pilot processing failed; no automatic retry"}, status=502)

            db = getattr(self.env, "HC_DB", None)
            preview = await process_preview(raw, metadata, db)
            metadata["preview_status"] = preview["status"]
            metadata["clarification_needed"] = bool(preview.get("clarification_needed"))
            mapping = configured_brands(str(getattr(self.env, "HELPCRUNCH_BRANDS_JSON", "") or ""))
            metadata["brand"] = brand_for_application(metadata["application_id"], mapping)
        except (TypeError, ValueError):
            return Response("Bad Request", status=400)
        # Dry-run planning only: no message text in logs or responses.
        # No outbound message or AI call. D1 writes only if HC_DB is configured.
        print("HELPCRUNCH EVENT", metadata)
        return Response.json({"ok": True, "mode": "receive-only"})
