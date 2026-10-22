-- Dedicated staging/production HelpCrunch D1 database only.
-- Do not apply to the legacy Telegram database.
CREATE TABLE IF NOT EXISTS hc_dialog_state (
  chat_id INTEGER NOT NULL,
  application_id INTEGER NOT NULL,
  state_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (chat_id, application_id)
);
CREATE TABLE IF NOT EXISTS hc_processed_events (
  event_key TEXT NOT NULL PRIMARY KEY,
  chat_id INTEGER NOT NULL,
  application_id INTEGER NOT NULL,
  processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_hc_processed_events_processed_at
  ON hc_processed_events(processed_at);
