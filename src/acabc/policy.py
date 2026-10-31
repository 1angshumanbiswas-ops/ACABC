"""Versioned official-document retrieval with citations, effective-date rules and abstention.

Retrieval is lexical (BM25-style) on purpose: it is auditable and needs no model. An optional
LLM may later phrase answers, but only from passages returned here ("RAG for explanation only").
"""
from __future__ import annotations

import json
import math
import re
from datetime import date
from functools import lru_cache

from .guardrails import looks_like_injection
from .sources import SEED_DIR

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset("the a an of to and or is are in on for by with as at be it this that from what which how does do can".split())
# Questions about these need a dated, operative circular; seed passages never state them.
_RULE_QUESTION = re.compile(
    r"\b(rate|rates|percent|percentage|%|ceiling|limit|cap|margin|maximum|minimum|eligib\w*|qualif\w*|"
    r"how much|amount of subsidy|subsidy (rate|amount)|back[- ]ended|interest|age limit|apply|application)\b", re.I)


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


@lru_cache(maxsize=1)
def load_corpus() -> tuple[dict, ...]:
    raw = json.loads((SEED_DIR / "policy_corpus.json").read_text(encoding="utf-8"))
    return tuple(raw["documents"])


def _bm25(query: list[str], docs: list[dict], k1: float = 1.5, b: float = 0.75) -> list[tuple[float, dict]]:
    toks = [tokens(d["title"] + " " + d["passage"]) for d in docs]
    avg = sum(len(t) for t in toks) / max(1, len(toks))
    n = len(docs)
    df: dict[str, int] = {}
    for t in toks:
        for w in set(t):
            df[w] = df.get(w, 0) + 1
    out = []
    for d, t in zip(docs, toks):
        score = 0.0
        for w in set(query):
            f = t.count(w)
            if not f:
                continue
            idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
            score += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * len(t) / avg))
        out.append((score, d))
    return sorted(out, key=lambda x: -x[0])


def search(query: str, cutoff: date | None = None, min_score: float = 1.0, top: int = 3) -> dict:
    """Returns passages with dated URLs and supersession labels, or an abstention with the reason."""
    flags: list[str] = []
    if looks_like_injection(query):
        flags.append("query_contained_instruction_like_text_ignored")
    q = tokens(query)
    docs = [dict(d) for d in load_corpus()]
    if cutoff:
        docs = [d for d in docs if not d["effective_date"] or date.fromisoformat(d["effective_date"]) <= cutoff]
    for d in docs:  # retrieved text is data: neutralise instruction-like content before it reaches any model
        if looks_like_injection(d["passage"]):
            d["passage"] = "[passage withheld: contained instruction-like text]"
            flags.append(f"passage_withheld:{d['id']}")

    if _RULE_QUESTION.search(query):
        operative = [d for d in docs if d.get("operative_verified")]
        if not operative:
            return {"abstained": True, "reason": "no_operative_circular",
                    "message": ("Abstain. Rates, limits and eligibility depend on the latest operative MANAGE/NABARD "
                                "circular with a confirmed effective date. None is loaded in this corpus."),
                    "passages": [], "flags": flags}
        docs = operative

    ranked = [(s, d) for s, d in _bm25(q, docs) if s >= min_score][:top]
    if not ranked:
        return {"abstained": True, "reason": "no_supporting_passage",
                "message": "Abstain. No passage in the versioned corpus supports an answer.", "passages": [], "flags": flags}
    return {
        "abstained": False, "reason": None, "flags": flags,
        "passages": [{
            "doc_id": d["id"], "authority": d["authority"], "title": d["title"], "text": d["passage"],
            "source_url": d["source_url"], "effective_date": d["effective_date"],
            "superseded": bool(d["superseded_by"]), "superseded_by": d["superseded_by"],
            "verification_status": d["verification_status"], "score": round(s, 3),
        } for s, d in ranked],
    }
