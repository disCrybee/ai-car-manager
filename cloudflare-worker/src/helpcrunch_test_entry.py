"""Isolated HelpCrunch receiver for safe staging; never sends chat replies."""
from workers import WorkerEntrypoint, Response
from urllib.parse import urlparse
import hmac
import json
from helpcrunch_groq import generate_reply
from helpcrunch_webhook import describe_event, verify_signature
from helpcrunch_brands import configured_brands, brand_for_application
from helpcrunch_planner import plan_incoming
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
                "groq_key_configured": bool(str(getattr(self.env, "GROQ_API_KEY", "") or ""))
            })
        if path == "/demo-groq":
            if request.method != "POST":
                return Response("Method Not Allowed", status=405)
            token = str(getattr(self.env, "HELPCRUNCH_DEMO_TOKEN", "") or "")
            supplied = request.headers.get("Authorization", "")
            if not token or not hmac.compare_digest(supplied, "Bearer " + token):
                return Response("Unauthorized", status=401)
            api_key = str(getattr(self.env, "GROQ_API_KEY", "") or "")
            if not api_key:
                return Response.json({"ok": False, "error": "Groq secret is not configured"}, status=503)
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
                # No arbitrary site identity, chat IDs, history or CRM data in demo.
                reply = await generate_reply(api_key, None, [{"role": "user", "content": user_text}])
                return Response.json({"ok": True, "reply": reply, "mode": "isolated-demo"})
            except (ValueError, TypeError):
                return Response("Bad Request", status=400)
            except Exception:
                print("HelpCrunch isolated Groq demo failed")
                return Response.json({"ok": False, "error": "Generation failed"}, status=502)
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
