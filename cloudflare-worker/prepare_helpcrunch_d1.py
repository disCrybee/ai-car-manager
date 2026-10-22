"""Prepare isolated HelpCrunch staging D1 config; never contacts Cloudflare.

Usage: python prepare_helpcrunch_d1.py <database-uuid> <existing-legacy-uuid>
Writes a separate wrangler.helpcrunch-d1.generated.json (gitignored).
The schema must be applied manually before deploying the generated config.
"""
import json
import re
import sys
from pathlib import Path

UUID = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")


def build_config(source: dict, database_id: str, legacy_id: str = "") -> dict:
    if not UUID.fullmatch(database_id):
        raise ValueError("Expected a Cloudflare D1 database UUID")
    if legacy_id and database_id.lower() == legacy_id.lower():
        raise ValueError("HelpCrunch must never reuse the legacy D1 database")
    if source.get("name") != "auction-auto-helpcrunch-test":
        raise ValueError("Not the isolated HelpCrunch test Worker")
    if source.get("main") != "src/helpcrunch_test_entry.py":
        raise ValueError("Unexpected entry point")
    if source.get("d1_databases"):
        raise ValueError("Source staging config must not already have a database")
    updated = dict(source)
    updated["d1_databases"] = [{
        "binding": "HC_DB",
        "database_name": "helpcrunch-test-memory",
        "database_id": database_id.lower(),
        "migrations_dir": "migrations/helpcrunch",
    }]
    return updated


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        raise SystemExit("Usage: python prepare_helpcrunch_d1.py <new-db-uuid> [legacy-db-uuid]")
    root = Path(__file__).resolve().parent
    original = json.loads((root / "wrangler.helpcrunch-test.jsonc").read_text())
    result = build_config(original, sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else "")
    dest = root / "wrangler.helpcrunch-d1.generated.json"
    dest.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Prepared {dest.name} — no Cloudflare changes made")
