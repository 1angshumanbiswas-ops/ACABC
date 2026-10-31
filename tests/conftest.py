import random

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from acabc.api import create_app
from acabc.ingest import load_private
from acabc.models import Role, ToolContext
from acabc.orchestrator import Orchestrator
from acabc.sources import load_seed
from acabc.state import build_state
from acabc.tools import ToolServer


@pytest.fixture()
def state():
    return build_state()


@pytest.fixture()
def orch(state):
    return Orchestrator(state)


@pytest.fixture()
def tools(state):
    return ToolServer(state)


@pytest.fixture()
def ctx():
    def make(role=Role.analyst, trace="t-test-0001"):
        return ToolContext(trace_id=trace, actor_role=role, dataset_version="seed-2026-10-26")
    return make


@pytest.fixture()
def client(state):
    return TestClient(create_app(state))


def hdr(role: str, actor: str = "tester") -> dict:
    return {"X-Actor-Role": role, "X-Actor-Id": actor}


@pytest.fixture()
def synthetic_file(tmp_path):
    """SYNTHETIC test fixture. Invented rows with invented column names; not ACABC data."""
    rnd = random.Random(7)
    rows = []
    for state, n, mean in (("Maharashtra", 80, 900_000), ("Uttar Pradesh", 70, 850_000), ("Tamil Nadu", 60, 880_000),
                           ("Odisha", 40, 820_000), ("Karnataka", 35, 870_000), ("Bihar", 30, 910_000), ("Sikkim", 4, 800_000),
                           ("Orissa", 5, 830_000)):  # 'Orissa' tests alias handling
        for _ in range(n):
            rows.append({"State Name": state, "Total Assistance (Rs)": round(rnd.gauss(mean, 60_000)),
                         "Enterprise Category": rnd.choice(["Agri-clinic", "Agri-business", "Input outlet"]),
                         "Applicant ID": f"SYN-{rnd.randrange(10**8):08d}", "Sanction Date": f"2024-0{rnd.randint(1, 9)}-1{rnd.randint(0, 9)}"})
    rows.append(dict(rows[0]))  # exact duplicate
    path = tmp_path / "synthetic_acabc.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


@pytest.fixture()
def schema_map():
    return {"rights": {"confirmed": True, "licensed_use": "synthetic test only", "authority": "test"},
            "dataset": {"version": "synthetic-test-v1"}, "units": {"assistance_amount": "rupee"},
            "fields": {"state": "State Name", "assistance_amount": "Total Assistance (Rs)", "enterprise_type": "Enterprise Category",
                       "beneficiary_key": "Applicant ID", "event_date": "Sanction Date"}}


@pytest.fixture()
def private_state(synthetic_file, schema_map):
    store = load_private(synthetic_file, schema_map, known_states=set(load_seed().states))
    return build_state(private=store)
