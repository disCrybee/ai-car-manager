# HelpCrunch integration (active development)

This is the **only target channel** for the new auto-consultant. Work on the feature branch without modifying the legacy production Worker from `main`.

## Runtime target

- `cloudflare-worker/src/helpcrunch_test_entry.py`: currently deployed staging receiver; **receive-only**, no customer-facing replies.
- `cloudflare-worker/wrangler.helpcrunch-test.jsonc`: isolated `auction-auto-helpcrunch-test` target.
- `cloudflare-worker/src/helpcrunch_*.py`: HelpCrunch API, webhook verification, brand identity, dialogue policy and qualification logic.
- `.github/workflows/deploy-helpcrunch-test.yml`: staging workflow.
- `cloudflare-worker/tests/test_helpcrunch*.py`: isolated tests.

## Retired prototype

Telegram-specific files remain solely as historical reference during migration. **Do not extend or deploy them for the HelpCrunch project.** In particular, the old `cloudflare-worker/src/entry.py` and `wrangler.jsonc` are NOT the staging entry point or staging config, and `bot.py` is not required for HelpCrunch.

**Before deleting the prototype**, migrate any reusable business/pricing logic to channel-neutral modules, verify all HelpCrunch tests, ensure the production deployment no longer relies on the old paths, and archive the last known working commit. Never merge a deletion that silently replaces an active production deployment.

## Functional target

- All approved websites managed by HelpCrunch; brand selected from trusted application ID mapping.
- Night shift 23:00–08:00 `Europe/Kyiv`.
- Natural professional sales consultation in the role of a junior sales representative, respectfully using formal address.
- Ask about ambiguous currencies and mileage units instead of assuming.
- Hand over only confirmed customer details to a senior manager through a verified HelpCrunch handoff.
- Dedicated `Андрій` agent account only after verifying its HelpCrunch ID and authorisation.
- Test-only outbound replies first; no automatic production replies until opt-in acceptance tests, deduplication, escalation, and rollback work.

