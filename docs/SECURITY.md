# Security and privacy notes

## Must change before any non-demo deployment

1. **Authentication.** `X-Actor-Role` is a header the caller controls. Replace `get_role` in `api.py` with a verified identity
   (OIDC/SSO) that issues the role claim, and bind reviewer identity (`X-Actor-Id`) to the token.
2. **Pepper.** `ingest.load_private(..., pepper=...)` defaults to a placeholder. Load a secret from a key manager. Rotate with care: it changes every beneficiary key.
3. **Storage.** The reference build is in-memory. Raw and identifiable data belongs in the `restricted` schema (see `sql/schema.sql`) with encryption at rest, key management, retention schedule and access logging.
4. **Rate limiting and request size limits** at the gateway.

## Data rules

- No ingestion without recorded rights (`rights.confirmed = true` and a non-empty `licensed_use`). This is the M0 go/no-go gate.
- Beneficiary and project identifiers are replaced with a keyed hash on load. Raw identifiers are not kept.
- Public outputs are aggregates with small-cell suppression. Export is masked and carries provenance and an artifact hash.
- Review the commencement dates and requirements of the Digital Personal Data Protection Act, 2023 and the DPDP Rules, 2025. Do not assume every provision is in force.
- Human review for every financial alert and intervention. No automated benefit exclusion, loan decision or fraud declaration. The disposition API has no "fraud" value.

## Threats covered by tests

Prompt injection in questions and retrieved passages, SQL-like input, unknown tool names, role escalation via arguments,
tampering with the audit chain, unit confusion (lakh vs crore), and fabricated dimensions.

## Threats not yet covered

Cross-tenant isolation (single tenant today), dependency and container scanning, penetration testing and incident-response runbook (M5).
