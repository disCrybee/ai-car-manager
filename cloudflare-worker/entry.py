from urllib.parse import urlparse

from workers import WorkerEntrypoint, Response


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        url = urlparse(request.url)
        path = url.path

        if path == "/health":
            return Response.json(
                {
                    "ok": True,
                    "service": "auction-auto-bot",
                    "runtime": "cloudflare-python-worker",
                }
            )

        if path != "/telegram-webhook":
            return Response("Not Found", status=404)

        if request.method != "POST":
            return Response("Method Not Allowed", status=405)

        received_secret = request.headers.get(
            "X-Telegram-Bot-Api-Secret-Token"
        )
        expected_secret = str(self.env.WEBHOOK_SECRET)

        if not received_secret or received_secret != expected_secret:
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

        if not chat_id:
            return Response.json({"ok": True})

        incoming_text = (message.get("text") or "").strip()

        if incoming_text == "/start":
            reply_text = (
                "✅ Auction Auto Bot працює через Cloudflare 24/7.\n\n"
                "Це тестова webhook-версія. Наступним кроком "
                "підключимо Groq та нашу логіку консультації."
            )
        else:
            reply_text = (
                "✅ Повідомлення отримано Cloudflare Worker.\n\n"
                f"Ви написали: {incoming_text or '[не текстове повідомлення]'}"
            )

        return Response.json(
            {
                "method": "sendMessage",
                "chat_id": chat_id,
                "text": reply_text,
            }
        )
