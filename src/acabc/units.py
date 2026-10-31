"""Indian currency units. Lakh/crore mix-ups are a named risk in the architecture (NABARD reports lakh)."""
from __future__ import annotations

LAKH = 100_000
CRORE = 10_000_000

_TO_RUPEES = {
    "rupee": 1, "rupees": 1, "inr": 1,
    "lakh": LAKH, "rupees_lakh": LAKH,
    "crore": CRORE, "rupees_crore": CRORE,
}
_CANON = {"rupee": "rupee", "rupees": "rupee", "inr": "rupee",
          "lakh": "lakh", "rupees_lakh": "lakh",
          "crore": "crore", "rupees_crore": "crore"}


def canonical_unit(unit: str) -> str:
    try:
        return _CANON[unit.strip().lower()]
    except KeyError as exc:
        raise ValueError(f"unknown currency unit: {unit!r}") from exc


def to_rupees(value: float, unit: str) -> float:
    return value * _TO_RUPEES[canonical_unit(unit)]


def from_rupees(rupees: float, unit: str) -> float:
    return rupees / _TO_RUPEES[canonical_unit(unit)]


def convert(value: float, src: str, dst: str) -> float:
    return from_rupees(to_rupees(value, src), dst)
