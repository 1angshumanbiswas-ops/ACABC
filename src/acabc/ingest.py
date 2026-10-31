"""Schema-map-driven ingestion of the record-level ACABC file (milestones M0/M1).

The real column names are not known yet. Ingestion therefore reads a TOML schema map that links
the architecture's logical fields to the actual columns once the AIKosh file is available.
Nothing is ingested unless the map records confirmed rights (the M0 go/no-go gate).
Beneficiary identifiers are never kept: they are replaced by a keyed hash.
"""
from __future__ import annotations

import hashlib
import hmac
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .units import to_rupees

LOGICAL_FIELDS = ("beneficiary_key", "project_key", "enterprise_type", "state", "district",
                  "assistance_amount", "event_date")
REQUIRED = ("state", "assistance_amount")

STATE_ALIASES = {
    "orissa": "Odisha", "uttaranchal": "Uttarakhand", "pondicherry": "Puducherry",
    "jammu and kashmir": "Jammu & Kashmir", "jammu & kashmir": "Jammu & Kashmir",
    "nct of delhi": "Delhi", "delhi (nct)": "Delhi", "new delhi": "Delhi",
    "andaman and nicobar islands": "Andaman & Nicobar Islands",
    "dadra and nagar haveli and daman and diu": "Dadra & Nagar Haveli and Daman & Diu",
    "telengana": "Telangana", "chattisgarh": "Chhattisgarh",
}


class IngestionError(RuntimeError):
    pass


@dataclass
class PrivateStore:
    df: pd.DataFrame
    mapping: dict
    report: dict
    source_file: str
    dataset_version: str
    columns_available: tuple[str, ...] = field(default_factory=tuple)

    def has(self, logical: str) -> bool:
        return logical in self.columns_available

    def profile(self) -> dict:
        return {"dataset_version": self.dataset_version, "source_file": self.source_file,
                "rows": int(len(self.df)), "logical_fields_mapped": list(self.columns_available),
                "ingestion_report": self.report, "rights": self.mapping.get("rights", {})}


def _canonical_state(raw: object, known: set[str]) -> str | None:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    text = " ".join(str(raw).strip().split())
    low = text.lower()
    if low in STATE_ALIASES:
        return STATE_ALIASES[low]
    for k in known:
        if k.lower() == low:
            return k
    return text  # kept as-is and reported as unmatched, never silently dropped


def _hash_key(value: object, pepper: bytes) -> str:
    return hmac.new(pepper, str(value).encode(), hashlib.sha256).hexdigest()[:16]


def load_schema_map(path: str | Path) -> dict:
    return tomllib.loads(Path(path).read_text(encoding="utf-8"))


def load_private(data_path: str | Path, schema_map: dict | str | Path, *,
                 known_states: set[str], pepper: bytes = b"change-me-in-production") -> PrivateStore:
    mapping = load_schema_map(schema_map) if not isinstance(schema_map, dict) else schema_map
    rights = mapping.get("rights", {})
    if not (rights.get("confirmed") is True and str(rights.get("licensed_use", "")).strip()):
        raise IngestionError("M0 gate: schema map must set rights.confirmed = true and rights.licensed_use "
                             "before any private-record ingestion.")
    fields = mapping.get("fields", {})
    missing_logical = [f for f in REQUIRED if f not in fields]
    if missing_logical:
        raise IngestionError(f"schema map lacks required logical fields: {missing_logical}")

    path = Path(data_path)
    raw = pd.read_csv(path, low_memory=False) if path.suffix.lower() == ".csv" else pd.read_excel(path)
    missing_cols = [c for c in fields.values() if c not in raw.columns]
    if missing_cols:
        raise IngestionError(f"mapped columns not present in file: {missing_cols}")

    out = pd.DataFrame(index=raw.index)
    report: dict = {"rows_in": int(len(raw))}
    for logical in LOGICAL_FIELDS:
        if logical in fields:
            out[logical] = raw[fields[logical]]

    out["state"] = out["state"].map(lambda v: _canonical_state(v, known_states))
    report["unmatched_states"] = sorted({s for s in out["state"].dropna().unique() if s not in known_states})
    report["null_states"] = int(out["state"].isna().sum())

    unit = mapping.get("units", {}).get("assistance_amount", "rupee")
    amount = pd.to_numeric(out["assistance_amount"], errors="coerce")
    report["non_numeric_amounts"] = int(amount.isna().sum() - out["assistance_amount"].isna().sum())
    out["assistance_amount"] = amount.map(lambda v: to_rupees(v, unit) if pd.notna(v) else v)
    report["amount_unit_in_file"] = unit
    report["negative_amounts"] = int((out["assistance_amount"] < 0).sum())

    if "event_date" in out:
        out["event_date"] = pd.to_datetime(out["event_date"], errors="coerce")
        report["unparseable_dates"] = int(out["event_date"].isna().sum())
    for key in ("beneficiary_key", "project_key"):
        if key in out:
            out[key] = out[key].map(lambda v: _hash_key(v, pepper))

    before = len(out)
    out = out.drop_duplicates()
    report["exact_duplicates_dropped"] = int(before - len(out))
    report["rows_out"] = int(len(out))
    if "district" in out:
        out["district"] = out["district"].astype("string").str.strip()
    version = mapping.get("dataset", {}).get("version") or f"private-{path.stem}"
    return PrivateStore(out.reset_index(drop=True), mapping, report, path.name, version,
                        tuple(c for c in LOGICAL_FIELDS if c in out.columns))
