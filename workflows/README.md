# Importable n8n workflows

Five inactive workflow templates are supplied. Their JSON structure is checked automatically; import and execution against your n8n installation still require validation. No credentials are included.

1. Start the local stack with `docker compose up -d`.
2. In n8n, import each JSON file from this folder.
3. Create MQTT credentials (`mosquitto:1883`) and Postgres credentials (`postgres:5432`, database/user `nmt`, password from `.env`). Assign them to every matching node. Leave MQTT JSON parsing off.
4. For accelerated simulation, run `UPDATE system_clock SET mode='simulation', simulated_at=NULL;` in Postgres before the first run. Import and activate Clock as well as Ingest. Clock messages are independent of device fixes. Use a fresh demo database for independent simulation runs; don't mix runs.
5. Evaluate writes changes into a durable notification queue. Deliver claims messages, sends them, and acknowledges only successful sends. Failed/unacknowledged messages become eligible after five minutes. Delivery is at-least-once: a crash after sending can cause a duplicate. Configure a Telegram credential and replace the chat ID before activating Deliver. Testing Telegram sends requires the account owner's authorization.
6. Activate API to expose `/webhook/latest`, available through nginx at `/api/latest`. Activate Ingest, Clock and Evaluate, then run the simulator.
7. For wall-clock use set `UPDATE system_clock SET mode='wall';`. This does not make the prototype suitable for real patient data.

## Verification checklist

- Publish a batch twice and confirm positions are not duplicated.
- Advance the clock 13 h without fixes: contact must become overdue.
- Disable the Telegram node: pending notifications must remain undelivered.
- Restore delivery and confirm acknowledgements are recorded.
- Disconnect the API: the dashboard must show an outage, retain previous data if any, and retry.

For an existing database, schema initialization does **not** rerun automatically. Back up first and use a new Compose project/volume for this version. Do not drop an existing database to install this release.

The exported templates use n8n's parameterized Postgres queries. See https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.postgres/ . Bind ports are localhost-only; anonymous MQTT remains a local synthetic-data convenience, not production security.
