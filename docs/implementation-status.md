# Implementation and validation status

## Added
- Responsive dashboard: fleet summaries, search, prioritised list, map reset, explicit demo/offline states, API retry and retained stale data.
- Root GitHub Pages entry opens the synthetic demo.
- Explicit wall/simulation clock, independently advanced through `nmt/clock`.
- Input shape and range checks; durable notification outbox with leased delivery and acknowledgement.
- Five inactive, credential-free n8n workflow templates.
- Adaptive communication experiment, 270 matched trials, paired uncertainty estimates and raw CSV.
- Simulator unit tests, SQL edge-case tests, database parity test, browser checks and GitHub Actions configuration.

## Remaining
- Import and execute n8n templates in a real n8n instance; confirm version compatibility and credentials.
- Authorised real Telegram delivery check. No messages have been sent.
- Production TLS, per-device identities, role-based access, audit/retention policies and independently reviewed clinical rules.
- Visit recording and clinician feedback are a later phase, not implemented here.
- Field validation, hardware calibration, official geography and ethical review are not completed.

Five local Python unit tests, JavaScript syntax validation, dashboard logic tests (coercion, search, HTML escaping, outage and recovery), and the 270-trial experiment runner passed. Browser and PostgreSQL checks are configured in CI; consult the actual workflow results rather than assuming success. Docker/n8n/Telegram integration is not represented by a passing SQL test.

Existing databases need a reviewed migration or a new isolated Compose project: modifying initialization SQL does not migrate an existing volume. Keep existing data intact.

GitHub branch creation was rejected with HTTP 403 by the current integration. No remote branch, pull request, CI run or deployment was created. Browser screenshots and PostgreSQL results for these changes are not yet available.
