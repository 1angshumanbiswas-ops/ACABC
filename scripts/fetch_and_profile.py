"""Download the ACABC dataset via the AIKosh SDK and write a schema-only profile.

Usage:
    pip install aikosh pandas openpyxl
    export AIKOSH_API_KEY="your key"      # Windows PowerShell: $env:AIKOSH_API_KEY="your key"
    python acabc_fetch_and_profile.py

Outputs ./downloads/dataset/... (raw file, keep private) and ./acabc_profile.json
(schema only, no row values for identifier-like columns; safe to share).
"""
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd

DEST = Path("./downloads/dataset")
IDENTIFIER = "a6dd19e7-89b7-4348-85fb-ccbf07af94fc"  # from the AIKosh SDK Access panel
PII_HINT = re.compile(
    r"name|phone|mobile|email|aadhaar|aadhar|pan\b|account|ifsc|address|pin|id$|_id|"
    r"beneficiary|applicant|contact|dob|birth",
    re.I,
)


def download() -> None:
    key = os.environ.get("AIKOSH_API_KEY")
    if not key:
        sys.exit("Set AIKOSH_API_KEY first (do not hard-code or share it).")
    import aikosh

    DEST.mkdir(parents=True, exist_ok=True)
    aikosh.set_api_key(key)
    aikosh.download(
        {
            "identifier": IDENTIFIER,
            "type": "dataset",
            "destination_path": str(DEST),
        }
    )


def find_table() -> Path:
    files = [p for p in DEST.rglob("*") if p.suffix.lower() in {".csv", ".xlsx", ".xls", ".json"}]
    if not files:
        sys.exit(f"No CSV/XLSX/JSON found under {DEST}. List the folder and tell me what is there.")
    files.sort(key=lambda p: p.stat().st_size, reverse=True)
    return files[0]


def load(path: Path) -> pd.DataFrame:
    s = path.suffix.lower()
    if s == ".csv":
        return pd.read_csv(path, low_memory=False)
    if s in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    return pd.read_json(path)


def profile(df: pd.DataFrame, path: Path) -> dict:
    out = {
        "file": path.name,
        "size_kb": round(path.stat().st_size / 1024, 2),
        "rows": int(len(df)),
        "columns": int(df.shape[1]),
        "full_row_duplicates": int(df.duplicated().sum()),
        "fields": [],
    }
    for c in df.columns:
        s = df[c]
        info = {
            "name": str(c),
            "dtype": str(s.dtype),
            "nulls": int(s.isna().sum()),
            "unique": int(s.nunique(dropna=True)),
        }
        looks_pii = bool(PII_HINT.search(str(c)))
        info["flagged_identifier_like"] = looks_pii
        if pd.api.types.is_numeric_dtype(s) and not looks_pii:
            d = s.describe()
            info.update(min=float(d["min"]), median=float(s.median()), max=float(d["max"]), sum=float(s.sum()))
        elif pd.api.types.is_datetime64_any_dtype(s):
            info.update(min=str(s.min()), max=str(s.max()))
        elif not looks_pii and info["unique"] <= 40:
            info["value_counts"] = {str(k): int(v) for k, v in s.value_counts().head(40).items()}
        out["fields"].append(info)
    return out


if __name__ == "__main__":
    if "--skip-download" not in sys.argv:
        download()
    table = find_table()
    frame = load(table)
    prof = profile(frame, table)
    Path("acabc_profile.json").write_text(json.dumps(prof, indent=2, ensure_ascii=False))
    print(f"{prof['rows']} rows x {prof['columns']} columns from {table.name}")
    for f in prof["fields"]:
        print(f"  {f['name']:<40} {f['dtype']:<10} nulls={f['nulls']} unique={f['unique']}")
    print("\nWrote acabc_profile.json (schema only). Upload that file here.")
