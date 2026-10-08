from urllib.parse import urlparse
from workers import WorkerEntrypoint, Response


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        path = urlparse(request.url).path

        if path == "/health":
            return Response.json({
                "ok": True,
                "service": "auction-auto-bot",
                "runtime": "cloudflare-python-worker"
            })

        if path != "/telegram-webhook":
            return Response("Auction Auto Worker is running", status=200)

        if request.method != "POST":
            return Response("Method Not Allowed", status=405)

        try:
            update = await request.json()
        except Exception:
            return Response("Bad Request", status=400)

        message = update.get("message")
        if not message:
            return Response.json({"ok": True})

        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        incoming_text = (message.get("text") or "").strip()

        if not chat_id:
            return Response.json({"ok": True})

        if incoming_text == "/start":
            reply_text = (
                "✅ Auction Auto Bot працює через Cloudflare 24/7.\n\n"
                "Це тестова webhook-версія."
            )
        else:
            reply_text = (
                "✅ Cloudflare отримав повідомлення.\n\n"
                f"Ви написали: {incoming_text or '[не текстове повідомлення]'}"
            )

        return Response.json({
            "method": "sendMessage",
            "chat_id": chat_id,
            "text": reply_text
        })
