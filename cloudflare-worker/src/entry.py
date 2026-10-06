from workers import WorkerEntrypoint, Response


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        url = str(request.url)

        if "/health" in url:
            return Response.json({
                "ok": True,
                "service": "auction-auto-bot",
                "runtime": "cloudflare-python-worker"
            })

        return Response(
            "Auction Auto Worker is running",
            status=200
        )
