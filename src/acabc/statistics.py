"""Robust statistics and interpretable clustering, in plain Python.

The clustering routine is a line-by-line port of the browser implementation in the IND_ACABC
app (including the mulberry32 PRNG), so the Python and HTML outputs agree and can be
cross-checked. Clusters are descriptive summaries, never rankings of states as good or bad.
"""
from __future__ import annotations

import math
from typing import Callable, Sequence

_M = 0xFFFFFFFF


def median(xs: Sequence[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        raise ValueError("median of empty sequence")
    m = n // 2
    return s[m] if n % 2 else (s[m - 1] + s[m]) / 2


def robust_z(xs: Sequence[float]) -> tuple[float, float, list[float]]:
    """Modified z-score 0.6745*(x-median)/MAD. Returns (median, MAD, scores). MAD==0 gives zeros."""
    med = median(xs)
    mad = median([abs(x - med) for x in xs])
    if mad == 0:
        return med, mad, [0.0 for _ in xs]
    return med, mad, [0.6745 * (x - med) / mad for x in xs]


def mulberry32(seed: int) -> Callable[[], float]:
    state = seed & _M

    def nxt() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & _M
        t = state
        t = ((t ^ (t >> 15)) * (1 | t)) & _M
        t = ((t + (((t ^ (t >> 7)) * (61 | t)) & _M)) & _M) ^ t
        return ((t ^ (t >> 14)) & _M) / 4294967296

    return nxt


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def standardise(rows: Sequence[Sequence[float]]) -> list[list[float]]:
    n, d = len(rows), len(rows[0])
    mu = [sum(r[j] for r in rows) / n for j in range(d)]
    sd = [math.sqrt(sum((r[j] - mu[j]) ** 2 for r in rows) / n) for j in range(d)]
    return [[(r[j] - mu[j]) / sd[j] if sd[j] else 0.0 for j in range(d)] for r in rows]


def _dist(a: Sequence[float], b: Sequence[float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def kmeans(X: list[list[float]], k: int, max_iter: int = 60) -> list[int]:
    n = len(X)
    order = sorted(range(n), key=lambda i: X[i][0])
    centres = [X[order[_round_half_up((i + 0.5) * (n - 1) / k)]][:] for i in range(k)]
    labels = [0] * n
    for _ in range(max_iter):
        changed = False
        for i, x in enumerate(X):
            best, bd = 0, 1e9
            for j, c in enumerate(centres):
                d = _dist(x, c)
                if d < bd:
                    bd, best = d, j
            if labels[i] != best:
                labels[i], changed = best, True
        for j in range(k):
            members = [X[i] for i in range(n) if labels[i] == j]
            if members:
                centres[j] = [sum(m[0] for m in members) / len(members), sum(m[1] for m in members) / len(members)]
        if not changed:
            break
    return labels


def rand_index(a: Sequence[int], b: Sequence[int]) -> float:
    n = len(a)
    agree = total = 0
    for i in range(n):
        for j in range(i + 1, n):
            total += 1
            if (a[i] == a[j]) == (b[i] == b[j]):
                agree += 1
    return agree / total


def silhouette(X: list[list[float]], labels: Sequence[int], k: int) -> float:
    tot = 0.0
    for i, x in enumerate(X):
        a_sum, a_n = 0.0, 0
        others = [[0.0, 0] for _ in range(k)]
        for j, y in enumerate(X):
            if i == j:
                continue
            d = _dist(x, y)
            if labels[j] == labels[i]:
                a_sum += d
                a_n += 1
            else:
                others[labels[j]][0] += d
                others[labels[j]][1] += 1
        a = a_sum / a_n if a_n else 0.0
        b = min((s / c for ci, (s, c) in enumerate(others) if ci != labels[i] and c), default=1e9)
        tot += (b - a) / max(a, b) if a_n and b < 1e9 else 0.0
    return tot / len(X)


def rule_groups(sizes: Sequence[float], k: int) -> list[int]:
    """Plain baseline: k equal-count groups by size. Clusters must beat this to be worth reporting."""
    n = len(sizes)
    order = sorted(range(n), key=lambda i: -sizes[i])
    out = [0] * n
    for rank, i in enumerate(order):
        out[i] = min(k - 1, (rank * k) // n)
    return out


def cluster_states(items: Sequence[dict], k: int, runs: int = 300, seed: int = 2026) -> dict:
    """items: [{'name', 'ventures', 'ratio'}] in a stable order. Features: log10(ventures) and ratio."""
    if k < 2 or len(items) < k + 2:
        raise ValueError("need k >= 2 and at least k+2 items")
    feats = lambda rows: standardise([[math.log10(r["ventures"]), r["ratio"]] for r in rows])  # noqa: E731
    X = feats(items)
    labels = kmeans(X, k)
    rnd = mulberry32(seed)
    m = _round_half_up(len(items) * 0.8)
    acc = 0.0
    for _ in range(runs):
        pool = list(range(len(items)))
        pick: list[int] = []
        while len(pick) < m:
            pick.append(pool.pop(int(math.floor(rnd() * len(pool)))))
        sub = kmeans(feats([items[i] for i in pick]), k)
        acc += rand_index(sub, [labels[i] for i in pick])
    stability = acc / runs
    sil = silhouette(X, labels, k)
    baseline = rand_index(labels, rule_groups([r["ventures"] for r in items], k))
    groups = []
    for c in range(k):
        mem = [items[i] for i in range(len(items)) if labels[i] == c]
        if mem:
            groups.append({
                "members": [x["name"] for x in mem],
                "n": len(mem),
                "mean_ventures": sum(x["ventures"] for x in mem) / len(mem),
                "mean_ratio": sum(x["ratio"] for x in mem) / len(mem),
            })
    groups.sort(key=lambda g: -g["mean_ventures"])
    good = stability >= 0.85 and sil >= 0.4
    return {
        "k": k, "n_items": len(items), "stability": stability, "silhouette": sil,
        "baseline_agreement": baseline, "groups": groups,
        "verdict": "stable_enough_to_describe" if good else "exploratory_only",
        "verdict_note": (
            "Stable enough to describe. High agreement with the plain size rule means the clusters add "
            "little beyond ranking by size: use them as a summary, not a finding."
            if good else
            "Exploratory only. Stability or separation is modest at this k, and the plain size rule "
            "groups the states about as well."
        ),
    }
