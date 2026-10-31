"""Request guardrails: what the system must never do, whatever the role.

No loan approval prediction, no fraud labels, no outcome (profit/survival) prediction, no
unsupported dimensions. Declines explain why and what is available instead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("loan_decision",
     re.compile(r"(loan|credit)\b.*\b(approv|predict|score|chance|sanction)|(approv|predict|sanction)\w*\b.*\b(loan|applicant|beneficiar)"
                r"|\bwill\b.*\b(get|receive)\b.*\b(loan|subsid|approv)", re.I),
     "Declined. No loan decisions or repayment outcomes exist in the data, and the system never automates "
     "approval, sanction or exclusion. Loan sanction rests with the financing institution."),
    ("fraud_label",
     re.compile(r"\b(fraud\w*|fake|cheat\w*|scam\w*|bogus|ghost beneficiar\w*)\b", re.I),
     "Declined. The system flags statistical outliers for human review. It does not label any person or "
     "state as fraudulent."),
    ("outcome_prediction",
     re.compile(r"\b(profit\w*|surviv\w*|success rate|default rate|will (it|they|this).*(succeed|fail))\b", re.I),
     "Declined. No enterprise outcome labels (profit, survival, closure, repayment) are available, so these "
     "cannot be estimated. Descriptive counts and ratios of cumulative totals are available instead."),
    ("district_dimension",
     re.compile(r"\bdistrict\w*\b", re.I),
     "Blocked. No district dimension exists in the loaded sources; state-level views only. District drill-down "
     "opens only after a record-level file with a verified district field is ingested."),
    ("beneficiary_identification",
     re.compile(r"\b(list|show|export|give)\b.*\b(names?|phone|mobile|aadhaar|aadhar|bank|account|address(es)?)\b.*\b(beneficiar\w*|applicant\w*|candidate\w*)"
                r"|\bwho (is|are) the beneficiar\w*", re.I),
     "Declined. Identifiable beneficiary data is never exposed. Only aggregates with small-cell suppression "
     "are available."),
    ("unrestricted_query",
     re.compile(r"\b(select\s+.+\s+from|drop\s+table|delete\s+from|insert\s+into|update\s+\w+\s+set|run sql|execute)\b", re.I),
     "Declined. No unrestricted SQL or write/execute operations are exposed. Use the bounded aggregate query."),
]

_INJECTION = re.compile(
    r"ignore (all |any )?(previous|prior|above) (instructions|rules)|disregard (the )?(system|previous)|"
    r"you are now|reveal (the )?(system )?prompt|act as (an? )?(admin|steward)|override (the )?(guardrails?|rbac)",
    re.I,
)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    code: str
    message: str


def check_request(text: str) -> Decision:
    for code, pattern, message in _RULES:
        if pattern.search(text):
            return Decision(False, code, message)
    return Decision(True, "ok", "Answerable from loaded sources.")


def looks_like_injection(text: str) -> bool:
    return bool(_INJECTION.search(text))
