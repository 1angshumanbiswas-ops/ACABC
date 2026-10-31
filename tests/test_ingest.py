"""Ingestion and private-data views, using a SYNTHETIC fixture (see conftest). Nothing here is ACABC data."""
import pytest

from acabc.ingest import IngestionError, load_private
from acabc.models import Role
from acabc.orchestrator import Orchestrator
from acabc.sources import load_seed
from conftest import hdr

KNOWN = set(load_seed().states)


def test_m0_gate_blocks_ingestion_without_confirmed_rights(synthetic_file, schema_map):
    for bad in ({"confirmed": False, "licensed_use": "x"}, {"confirmed": True, "licensed_use": ""}, {}):
        with pytest.raises(IngestionError, match="M0 gate"):
            load_private(synthetic_file, {**schema_map, "rights": bad}, known_states=KNOWN)


def test_missing_mapped_column_is_an_error_not_a_guess(synthetic_file, schema_map):
    bad = {**schema_map, "fields": {**schema_map["fields"], "state": "No Such Column"}}
    with pytest.raises(IngestionError, match="not present"):
        load_private(synthetic_file, bad, known_states=KNOWN)
    with pytest.raises(IngestionError, match="required"):
        load_private(synthetic_file, {**schema_map, "fields": {"state": "State Name"}}, known_states=KNOWN)


def test_ingestion_report_and_identifier_hashing(synthetic_file, schema_map):
    p = load_private(synthetic_file, schema_map, known_states=KNOWN)
    assert p.report["exact_duplicates_dropped"] == 1 and p.report["unmatched_states"] == [] and "Orissa" not in set(p.df["state"])
    assert "Odisha" in set(p.df["state"])
    assert p.df["beneficiary_key"].str.fullmatch(r"[0-9a-f]{16}").all() and not p.df["beneficiary_key"].str.contains("SYN").any()
    assert not p.has("district") and p.has("enterprise_type")


def test_unit_conversion_on_ingest(synthetic_file, schema_map):
    a = load_private(synthetic_file, schema_map, known_states=KNOWN)
    b = load_private(synthetic_file, {**schema_map, "units": {"assistance_amount": "lakh"}}, known_states=KNOWN)
    assert b.df["assistance_amount"].iloc[0] == pytest.approx(a.df["assistance_amount"].iloc[0] * 100_000)


def test_private_aggregates_suppress_small_cells_and_block_unmapped_district(private_state):
    o = Orchestrator(private_state)
    ctx = o.context(Role.analyst)
    r = o.tools.call("acabc.aggregate_query", {"metric": "records", "group_by": "state"}, ctx)
    by = {x["key"]: x for x in r.data["rows"]}
    assert by["Sikkim"]["suppressed"] and by["Sikkim"]["value"] is None  # 4 records < 10
    assert by["Maharashtra"]["value"] == 80  # 80 generated + 1 exact duplicate removed on ingest
    assert by["Odisha"]["value"] == 45       # 40 'Odisha' + 5 'Orissa' merged by alias
    steward = o.tools.call("acabc.aggregate_query", {"metric": "records", "group_by": "state"}, o.context(Role.steward))
    assert {x["key"]: x for x in steward.data["rows"]}["Sikkim"]["value"] == 4
    d = o.tools.call("acabc.aggregate_query", {"metric": "records", "group_by": "district"}, ctx)
    assert not d.ok and d.error["code"] == "dimension_unavailable"
    assert o.tools.call("acabc.aggregate_query", {"metric": "records"}, o.context(Role.public)).error["code"] == "forbidden"


def test_enterprise_segments_light_up_when_field_is_mapped(private_state):
    o = Orchestrator(private_state)
    d = o.run_agent("01", o.context(Role.analyst)).data["enterprise_segments"]
    assert d["available"] and {r["key"] for r in d["rows"]} == {"Agri-clinic", "Agri-business", "Input outlet"}


def test_private_dataset_version_flows_through_context_and_profile(private_state):
    o = Orchestrator(private_state)
    assert o.context(Role.analyst).dataset_version == "synthetic-test-v1"
    prof = o.tools.call("acabc.dataset_profile", {}, o.context(Role.steward)).data["private_record_level"]
    assert prof["rows"] > 300 and "beneficiary_key" in prof["logical_fields_mapped"] and prof["rights"]["confirmed"]


def test_private_validate_and_screen(private_state):
    o = Orchestrator(private_state)
    v = o.tools.call("acabc.validate_financials", {"group": "private", "metric": "assistance_amount", "unit": "rupee"}, o.context(Role.analyst)).data
    assert v["unit_consistent"] and v["duplicates"] == 1
    bad = o.tools.call("acabc.validate_financials", {"group": "private", "metric": "assistance_amount", "unit": "crore"}, o.context(Role.analyst)).data
    assert bad["status"] == "fail"
    res = o.run_agent("02", o.context(Role.analyst))
    assert res.data["private_groups"]["rows"] and all(r["n_records"] >= 10 for r in res.data["private_groups"]["rows"])


def test_api_with_private_data_exposes_district_only_if_mapped(private_state):
    from fastapi.testclient import TestClient
    from acabc.api import create_app
    c = TestClient(create_app(private_state))
    cov = c.get("/v1/coverage", headers=hdr("analyst")).json()
    assert cov["geography"]["district_available"] is False and "enterprise_type" in cov["record_level_fields"]
    assert "record_level_fields" not in c.get("/v1/coverage").json()  # public never sees record-level field names
