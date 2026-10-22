"""Isolated HelpCrunch receiver for safe staging; never sends chat replies."""
from workers import WorkerEntrypoint, Response
from urllib.parse import urlparse
from helpcrunch_webhook import describe_event, verify_signature
from helpcrunch_brands import configured_brands, brand_for_application
from helpcrunch_planner import plan_incoming


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        path = urlparse(request.url).path
        if path == "/health":
            return Response.json({"ok": True, "service": "helpcrunch-test", "mode": "receive-only"})
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
            metadata["clarification_needed"] = bool(plan["suggested_reply"])
            mapping = configured_brands(str(getattr(self.env, "HELPCRUNCH_BRANDS_JSON", "") or ""))
            metadata["brand"] = brand_for_application(metadata["application_id"], mapping)
        except (TypeError, ValueError):
            return Response("Bad Request", status=400)
        # Dry-run planning only: no message text in logs or responses.
        # No outbound message, no AI call, no D1 write.
        print("HELPCRUNCH EVENT", metadata)
        return Response.json({"ok": True, "mode": "receive-only"})
