from urllib.parse import urlparse
from workers import WorkerEntrypoint, Response


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        url = urlparse(request.url)

        # Health check
        if url.path == "/health":
            return Response.json({
                "ok": True,
                "service": "auction-auto-bot",
                "runtime": "cloudflare-python-worker"
            })

        # Telegram webhook endpoint
        if url.path == "/telegram-webhook":
            if request.method != "POST":
                return Response("Method Not Allowed", status=405)

            expected_secret = str(self.env.WEBHOOK_SECRET)
            received_secret = request.headers.get(
                "X-Telegram-Bot-Api-Secret-Token"
            )

            if received_secret != expected_secret:
                return Response("Unauthorized", status=403)

            try:
                update = await request.json()
            except Exception:
                return Response("Bad Request", status=400)

            message = update.get("message")
            if not message:
                return Response.json({"ok": True})

            chat = message.get("chat") or {}
            chat_id = chat.get("id")
            text = (message.get("text") or "").strip()

            if not chat_id:
                return Response.json({"ok": True})

            if text == "/start":
                reply_text = (
                    "✅ Auction Auto Bot працює через Cloudflare 24/7.\n\n"
                    "Це тестова webhook-версія."
                )
            else:
                reply_text = (
                    "✅ Cloudflare отримав повідомлення.\n\n"
                    f"Ви написали: {text or '[не текстове повідомлення]'}"
                )

            # Telegram supports calling Bot API methods directly
            # in the webhook HTTP response.
            return Response.json({
                "method": "sendMessage",
                "chat_id": chat_id,
                "text": reply_text
            })

        return Response("Auction Auto Worker is running", status=200)
