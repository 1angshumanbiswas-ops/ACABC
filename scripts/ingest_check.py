"""M0/M1 gate check: load the record-level file through the schema map and print the ingestion report.

    python scripts/ingest_check.py path/to/file.csv config/schema_map.toml

Prints counts and issues only, never row values.
"""
import json
import sys

from acabc.ingest import IngestionError, load_private
from acabc.sources import load_seed


def main(data: str, schema_map: str) -> int:
    try:
        store = load_private(data, schema_map, known_states=set(load_seed().states))
    except IngestionError as exc:
        print("BLOCKED:", exc)
        return 1
    print(json.dumps(store.profile(), indent=2, default=str))
    issues = [k for k, v in store.report.items() if k in {"unmatched_states", "null_states", "non_numeric_amounts", "negative_amounts", "unparseable_dates"} and v]
    print("\nISSUES TO RESOLVE BEFORE M1 SIGN-OFF:" if issues else "\nNo high-severity ingestion issues found.", issues or "")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
