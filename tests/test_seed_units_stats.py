import pytest

from acabc.audit import AuditLog
from acabc.sources import load_seed, verify_seed
from acabc.statistics import cluster_states, median, mulberry32, robust_z
from acabc.units import convert, from_rupees, to_rupees


def test_every_seed_integrity_check_passes():
    failed = [c for c in verify_seed() if not c["passed"]]
    assert not failed, failed


def test_known_official_figures():
    b = load_seed().benchmarks
    assert (b["mis_2026-10-26"]["values"]["trained"], b["mis_2026-10-26"]["values"]["ventures"]) == (96306, 42916)
    assert (b["manage_statewise_2026-10-01"]["values"]["trained"], b["manage_statewise_2026-10-01"]["values"]["ventures"]) == (97347, 42768)
    assert (b["nabard_xii_f_fy2026-27"]["values"]["schemes"], b["nabard_xii_f_fy2026-27"]["values"]["subsidy_released"]) == (245, 1135.03)


def test_units_lakh_is_not_crore():
    assert to_rupees(1135.03, "lakh") == pytest.approx(113_503_000)
    assert convert(1135.03, "lakh", "crore") == pytest.approx(11.3503)
    assert from_rupees(10_000_000, "crore") == 1
    with pytest.raises(ValueError):
        to_rupees(1, "dollars")


def test_robust_z_is_not_distorted_by_one_extreme_value():
    med, mad, z = robust_z([5, 5.2, 5.4, 5.6, 5.8, 6.0, 500])
    assert med == 5.6 and z[-1] > 100 and max(abs(x) for x in z[:-1]) < 2
    assert robust_z([3, 3, 3])[2] == [0.0, 0.0, 0.0]
    assert median([4, 1, 3, 2]) == 2.5


def test_mulberry32_matches_javascript_reference():
    # Values produced by the IND_AGRI_APP v1.2 JavaScript implementation (node) for seed 2026.
    g = mulberry32(2026)
    assert [g(), g(), g()] == pytest.approx([0.45540769933722913, 0.30849614599719644, 0.6611574492417276], abs=1e-15)


@pytest.mark.parametrize("k,stab,sil,base", [
    (2, 0.6940740740740716, 0.36839509944904675, 0.6086956521739131),
    (3, 0.9114424951267047, 0.39976359107470705, 0.8007246376811594),
    (4, 0.8718518518518499, 0.3448188238522299, 0.8659420289855072),
    (5, 0.8960038986354757, 0.3513786802952717, 0.8115942028985508),
])
def test_clustering_matches_javascript_reference(k, stab, sil, base):
    items = [{"name": r.state, "ventures": r.ventures, "ratio": r.ventures / r.trained}
             for r in load_seed().manage if r.trained >= 100 and r.ventures > 0]
    assert len(items) == 24
    c = cluster_states(items, k)
    assert c["stability"] == pytest.approx(stab, abs=1e-12)
    assert c["silhouette"] == pytest.approx(sil, abs=1e-9)
    assert c["baseline_agreement"] == pytest.approx(base, abs=1e-12)


def test_audit_chain_detects_tampering():
    log = AuditLog()
    for i in range(5):
        log.append(trace_id="t", event="x", i=i)
    assert log.verify()
    log._entries[2]["i"] = 99
    assert not log.verify()
