# n8n workflows

All logic lives in PostgreSQL (`db/01_schema.sql`), so each workflow is a thin pipe: **one trigger, one SQL call, one output**. Build the three workflows below in the n8n editor (http://localhost:5678), activate them, then **export each as JSON into this folder** (`⋯ → Download`) so the repo contains them.

## Credentials (create once)

| Credential | Settings |
|---|---|
| **MQTT** | Host `mosquitto`, port `1883`, no username/password (dev only) |
| **Postgres** | Host `postgres`, database `nmt`, user `nmt`, password = `POSTGRES_PASSWORD` from `.env`, port `5432`, SSL off |
| **Telegram** | Bot token from [@BotFather](https://t.me/BotFather). To get your chat ID, message the bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` |

Inside Docker the services reach each other by service name (`mosquitto`, `postgres`), not `localhost`.

## 1. `NMT – Ingest`

```
MQTT Trigger ──► Postgres (Execute Query)
```

* **MQTT Trigger**
  * Topics: `nmt/tracker/+/batch`
  * Options: leave *JSON Parse Body* **off**, so `$json.message` is the raw payload string.
* **Postgres → Execute Query**
  * Query: `SELECT ingest_batch_b64($1) AS inserted;`
  * Options → Query Parameters: `{{ $json.message.base64Encode() }}`
    (fallback if your n8n version lacks it: `{{ btoa($json.message) }}`)

Why base64? The payload is JSON full of commas, and n8n splits query parameters on commas. Base64 also guarantees the payload is passed as a **parameter**, never concatenated into SQL (no injection). Re-delivered points are ignored by the `UNIQUE (device_id, recorded_at)` constraint, so satellite heartbeats and later cellular batches can overlap safely.

## 2. `NMT – Alerts`

```
Schedule Trigger (every 1 min) ──► Postgres (Execute Query) ──► Telegram (Send Message)
```

* **Postgres**: `SELECT * FROM evaluate_alerts();`
  Returns only *changes* since the last run: rows with `event = opened | resolved`. A partial unique index keeps at most one open alert per mother and type, so there is no alert spam.
* **Telegram → Send Message**: Chat ID = yours, Text = `{{ $json.message }}`
  When nothing changed, the Postgres node returns 0 items and Telegram is not called.

Alert types: `LOW_BATTERY`, `LOST_CONTACT` (with *likely dead battery* vs *out of coverage*), `CROSSED_BORDER` (plus a *back in Kenya* resolution), `ANC_OVERDUE`.

## 3. `NMT – API`

```
Webhook (GET /latest) ──► Postgres (Execute Query) ──► Respond to Webhook
```

* **Webhook**: Method `GET`, Path `latest`, Respond: *Using 'Respond to Webhook' node*
* **Postgres**: `SELECT * FROM latest_status ORDER BY priority DESC, alias;`
* **Respond to Webhook**: Respond With *All Incoming Items*

Nginx forwards `http://localhost:8080/api/latest` → `http://n8n:5678/webhook/latest`, so the dashboard and API share an origin (no CORS setup). The production URL works only when the workflow is **active**.

## Checking that it works

```sql
-- docker compose exec postgres psql -U nmt -d nmt
SELECT link, buffered, count(*) FROM positions GROUP BY 1, 2;   -- cell vs sat, live vs store-and-forward
SELECT status, count(*) FROM latest_status GROUP BY 1;
SELECT alert_type, count(*) FILTER (WHERE resolved_at IS NULL) AS open FROM alerts GROUP BY 1;
```
