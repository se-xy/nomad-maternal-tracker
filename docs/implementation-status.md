# Implementation and validation status

Last updated: 3 November 2026.

## Built
- Desert-aware tracker simulator (movement, heat, solar, cell coverage, store-and-forward, satellite heartbeat, border crossings).
- PostgreSQL logic: input validation, idempotent ingestion, explicit wall/simulation clock advanced through `nmt/clock`, status view, priority score, alert engine, durable notification outbox with leased delivery and acknowledgement.
- Responsive dashboard: fleet summaries, search, prioritised list, map reset, explicit demo/offline states, API retry with retained stale data. GitHub Pages always serves the labelled synthetic demo.
- Five inactive, credential-free n8n workflow templates (Ingest, Clock, Evaluate, Deliver, API).
- Communication-policy experiment: 270 matched trials, paired bootstrap intervals, raw CSV.
- Tests and CI (see below).

## Verified
| Check | Where | Result |
|---|---|---|
| Simulator unit tests | Local + GitHub Actions | Pass |
| Database parity (SQL view vs simulator model, 30 mothers) | Local PostgreSQL 16 + GitHub Actions | 0 mismatches, 0 duplicate open alerts |
| SQL edge cases (dedup, invalid input, clock outage, outbox lease) | Local PostgreSQL 16 + GitHub Actions | Pass |
| Dashboard logic (coercion, search, escaping, outage, recovery) | Local Node 22 + GitHub Actions | Pass |
| Browser checks, desktop and mobile (Chromium) | Local + GitHub Actions | Pass |
| Experiment re-run (270 trials) | Local | Identical to `experiments/results.csv` |
| Live MQTT publishing from the simulator | Local test broker | Messages received with correct topic and payload |

## Not yet verified
- The full Docker Compose stack (Mosquitto, Postgres, n8n, nginx) has not been started end to end.
- The n8n templates have not been imported or executed in a real n8n instance; version compatibility and credentials are unconfirmed.
- Telegram delivery has not been tested. No messages have been sent.

## Out of scope for this prototype
- **Real data.** Real tracking and health records are protected health data under Kenya's Data Protection Act (2019), would expose vulnerable people in a border region if leaked, and are not available to this independent project. All data is synthetic; see the README section "Why the data is simulated".
- Production TLS, per-device identities, role-based access, audit and retention policies.
- Visit recording, clinician feedback and independently reviewed clinical rules.
- Field validation, hardware calibration, official geography and ethical review.

Existing databases need a reviewed migration or a new isolated Compose project: changing the initialisation SQL does not migrate an existing volume.
