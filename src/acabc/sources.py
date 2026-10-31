"""Source registry: loads the seeded official aggregates and checks their internal integrity.

Every record keeps agency, scope, reference date, unit and cumulative-vs-FY status. Different
government reports are different data products and are never silently merged or averaged.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

SEED_DIR = Path(__file__).parent / "seed"
SEED_VERSION = "seed-2026-10-26"


@dataclass(frozen=True)
class StateRow:
    state: str
    trained: int
    ventures: int


@dataclass(frozen=True)
class NabardRow:
    state: str
    schemes: int
    subsidy_lakh: float


@dataclass(frozen=True)
class Seed:
    manage: tuple[StateRow, ...]
    nabard: tuple[NabardRow, ...]
    benchmarks: dict[str, dict]
    quality_report: dict

    @property
    def states(self) -> tuple[str, ...]:
        return tuple(r.state for r in self.manage)

    def nabard_by_state(self) -> dict[str, NabardRow]:
        return {r.state: r for r in self.nabard}


@lru_cache(maxsize=1)
def load_seed() -> Seed:
    with (SEED_DIR / "manage_statewise_2026-10-01.csv").open(encoding="utf-8", newline="") as fh:
        manage = tuple(StateRow(r["state"], int(r["trained"]), int(r["ventures"])) for r in csv.DictReader(fh))
    with (SEED_DIR / "nabard_xii_f_fy2026-27_to_2026-09-30.csv").open(encoding="utf-8", newline="") as fh:
        nabard = tuple(
            NabardRow(r["state"], int(r["schemes"]), float(r["subsidy_released_lakh"])) for r in csv.DictReader(fh)
        )
    raw = json.loads((SEED_DIR / "benchmarks.json").read_text(encoding="utf-8"))
    return Seed(manage, nabard, {b["id"]: b for b in raw["benchmarks"]}, raw["dataset_quality_report"])


def verify_seed(seed: Seed | None = None) -> list[dict]:
    """Integrity checks run in tests and at /healthz. Each check has a name, pass flag and detail."""
    s = seed or load_seed()
    mis = s.benchmarks["mis_2026-10-26"]
    mg = s.benchmarks["manage_statewise_2026-10-01"]
    nb = s.benchmarks["nabard_xii_f_fy2026-27"]
    sub_sum = round(sum(r.subsidy_lakh for r in s.nabard), 2)
    era_a, era_b = mis["detail"]["era_2002_2017"], mis["detail"]["era_2018_onward_mis"]
    unknown = sorted(set(r.state for r in s.nabard) - set(s.states))
    checks = [
        ("manage_rows_sum_to_total_trained", sum(r.trained for r in s.manage) == mg["values"]["trained"],
         f'{sum(r.trained for r in s.manage)} vs {mg["values"]["trained"]}'),
        ("manage_rows_sum_to_total_ventures", sum(r.ventures for r in s.manage) == mg["values"]["ventures"],
         f'{sum(r.ventures for r in s.manage)} vs {mg["values"]["ventures"]}'),
        ("mis_eras_sum_to_cumulative_trained", era_a["trained"] + era_b["trained"] == mis["values"]["trained"], ""),
        ("mis_eras_sum_to_cumulative_ventures", era_a["ventures"] + era_b["ventures"] == mis["values"]["ventures"], ""),
        ("nabard_scheme_counts_sum_to_245", sum(r.schemes for r in s.nabard) == nb["values"]["schemes"],
         str(sum(r.schemes for r in s.nabard))),
        ("nabard_subsidy_sum_within_printed_rounding",
         abs(sub_sum - nb["values"]["subsidy_released"]) < 0.05,
         f'state sum {sub_sum} vs printed {nb["values"]["subsidy_released"]} lakh'),
        ("nabard_states_exist_in_manage_list", not unknown, ", ".join(unknown)),
        ("no_duplicate_manage_states", len(set(s.states)) == len(s.states), ""),
    ]
    return [{"check": n, "passed": bool(p), "detail": d} for n, p, d in checks]
