# Read-only learning from manager replies

`HELPCRUNCH_LEARNING_ENABLED=true` enables a separate scheduled knowledge process.
It does not fine-tune model weights or edit the fixed conversation policy.

## Collection and use

- Every five minutes, the schedule checks Kyiv time. Collection runs only 08:00–23:00.
- Uses only GET /chats and GET /chats/{id}/messages. It does not mark messages read,
  change chat status/assignees, create notes or send messages.
- Pages through chats with activity in the last 30 days, ten records at a time,
  processing at most two changed chats per run. The cursor resumes on the next run.
  It cycles to recent chats when the end of the window is reached; busy inboxes take
  multiple runs. Each chat contributes at most its 100 most recent messages.
- Only public, non-broadcast daytime manager messages from configured application
  IDs are considered. Customer messages, private notes and attachments are excluded.
- Shared human/AI agent 21 is excluded entirely to prevent learning from the bot's
  own historical replies, including when older bot IDs have left the guard history.
  Human replies from that shared account therefore do not contribute knowledge.
- Names available in chat metadata, contacts, links and VIN-like strings are redacted
  before model extraction. Raw transcripts are not stored in the knowledge tables.
- AI proposes up to three exact excerpts from manager replies. Code validates exact
  source matching and rejects numbers, prices, contact data, operational instructions,
  promises and common sensitive terms. A second AI pass checks generality, privacy,
  conflicts with existing knowledge and consistency with the fixed sales policy.
- Only general automotive explanations are automatically retained. Company terms,
  fees, current inventory, prices and delivery promises must still come from the
  existing verified data, not manager conversations. Automated screening is not a
  guarantee of factual correctness; the responder is instructed to defer if uncertain.
- Excerpts retain application/chat/message/agent provenance, expire 30 days after
  their source message, and are replaced when the source chat changes and is rescanned.
  Edits that do not change the chat's lastMessageId/lastMessageAt may remain until expiry.
- Night replies retrieve at most three relevant excerpts from the same application.
  They are passed as lower-priority reference data, never inserted into system policy.
  Fixed policies, deterministic answers and verified shipping prices take precedence.
- Failed learning or retrieval does not disable normal consultation. Existing manual
  takeover checks and the final 23:00-inclusive / 08:00-exclusive send gate remain.

## Operations

The three `hc_learning_*` / `hc_manager_knowledge` tables are created idempotently
by the scheduled process in HC_DB. No legacy tables are migrated or replaced.
An expiring database lease prevents overlapping scheduled runs.

`GET /health` reports `learning_enabled` and an aggregate last-run status without
transcripts or customer identifiers. `not-run-yet` means no completed run is recorded;
`ok` with zero excerpts can simply mean nothing suitable was found. `partial` / `error`
requires checking the logs; log messages contain exception types only.

Set `HELPCRUNCH_LEARNING_ENABLED=false` to stop both collection and retrieval without
changing the existing night bot. Stored excerpts are then unused. Changing
`POLICY_VERSION` invalidates existing excerpts when extraction rules change.

## Verification

Run `python -m unittest discover -s tests -p 'test_helpcrunch*.py'`.
Tests cover extraction evidence, audit rejection, privacy filters, application
isolation, expiry, D1 persistence, leases, retries, bounded paging, prompt priority
and existing time/takeover protections. No test sends real customer messages.
