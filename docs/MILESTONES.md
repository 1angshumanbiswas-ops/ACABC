# Milestones and gates

| Milestone | Work package | Gate | Status |
|---|---|---|---|
| **M0** rights and data | Obtain the actual ACABC file, dictionary, provenance, reporting period and rights | Go/no-go for private records | **Blocked**: AIKosh returned "no permission to download"; access request needed (`DATA_ACCESS.md`) |
| **M1** source integrity | Validated ETL, state/district mapping, discrepancy register | Official totals and units reproduced | Aggregates done and tested; ISO/LGD codes and real file pending |
| **M2** usable product | Dashboard, geography/finance explorer, evidence exports | Approved users complete five scripted demos | API and exports done; dashboard is the separate single-file HTML app |
| **M3** ML demonstration | Fit baselines, screen examples, label a sample, evaluate | Documented baselines and false positives | Clustering and MAD screen on aggregates done; record-level screening and labels pending |
| **M4** policy QA | Curated official circular corpus, citation checks, safety tests | Reviewer validates critical answers | Retrieval, abstention and injection tests done; official text curation pending |
| **M5** production controls | Security audit, monitoring, RBAC, runbook, evaluation pack | Release checklist signed | Not started (see `SECURITY.md`) |

## Evaluation gates (provisional, not achieved results)

Source reconciliation reproduces 100% of chosen benchmark totals (passing for seed aggregates). Anomaly precision@k targets are set only after
class balance is observed on a labelled sample. Clustering must beat the plain size rule on stability and expert relevance, otherwise the product stays descriptive.
A negative result is valid.
