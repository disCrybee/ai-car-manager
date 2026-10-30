"""Safe staging configuration checks for dedicated HelpCrunch D1.

Runs as ordinary Python in CI; does not contact Cloudflare or change resources.
"""
import json
from pathlib import Path


def validate_staging_config(config: dict) -> bool:
    if config.get("name") != "auction-auto-helpcrunch-test":
        raise ValueError("Unexpected Worker")
    if config.get("main") != "src/helpcrunch_test_entry.py":
        raise ValueError("Unexpected entry point")
    bindings = config.get("d1_databases", [])
    if len(bindings) > 1:
        raise ValueError("Only one staging D1 binding is allowed")
    if bindings:
        b = bindings[0]
        if b.get("binding") != "HC_DB" or b.get("database_name") != "helpcrunch-test-memory":
            raise ValueError("Unexpected D1 binding")
        if not b.get("database_id"):
            raise ValueError("D1 UUID missing")
    return True


def assert_schema_file(root: Path) -> bool:
    path = root / "migrations" / "helpcrunch" / "0001_dialog_state.sql"
    schema = path.read_text(encoding="utf-8")
    if "hc_dialog_state" not in schema or "hc_processed_events" not in schema:
        raise ValueError("Required schema tables are missing")
    return True


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    validate_staging_config(json.loads((root / "wrangler.helpcrunch-test.jsonc").read_text()))
    assert_schema_file(root)
    print("Staging config and schema references verified (no network operations).")
