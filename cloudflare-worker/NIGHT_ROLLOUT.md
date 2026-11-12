# Night rollout checklist

Staging Worker only. Main and Bitrix24 unchanged.

1. Verify GitHub Actions green and staging /health available.
2. Get actual application IDs from HelpCrunch GET /v1/applications (authenticated).
3. Set HELPCRUNCH_BRANDS_JSON to JSON mapping exact application IDs to display brand names. For illustration only: {"123":"Auction Auto"}. Never use the example ID.
4. Set HELPCRUNCH_NIGHT_ENABLED=true and HELPCRUNCH_NIGHT_SEND_ENABLED=true in the staging Cloudflare Worker. Both must be true to send.
5. Ensure HC_DB, GROQ_API_KEY, HELPCRUNCH_API_KEY and webhook signing key remain configured.
6. Verify HelpCrunch customer-message webhook targets staging Worker exactly once.
7. Check messages during 23:00-08:00 Europe/Kyiv; manually reply as agent 21 to test takeover.
8. Emergency stop: set HELPCRUNCH_NIGHT_SEND_ENABLED=false.

Unknown brand, daytime, unexpected history, and manual operator replies fail closed. Phone-based completion is isolated by chat. The existing HelpCrunch-to-Bitrix24 integration continues independently. Do not paste tokens in chat or GitHub.

No production readiness claim until observing a live night shift.