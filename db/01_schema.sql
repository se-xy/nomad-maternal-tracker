-- Nomad Maternal Tracker: schema, ingestion, status view and alert engine.
-- All business logic lives here so n8n workflows stay thin (one SQL call each).

-- ---------------------------------------------------------------- reference data
CREATE TABLE outreach_bases (
    name text PRIMARY KEY,
    lat  double precision NOT NULL,
    lon  double precision NOT NULL
);

-- Kenya-Ethiopia border as an ordered polyline (west -> east). Approximate; see geo/region.json.
CREATE TABLE border_vertices (
    seq int PRIMARY KEY,
    lon double precision NOT NULL,
    lat double precision NOT NULL
);

-- ---------------------------------------------------------------- core tables
CREATE TABLE devices (
    device_id text PRIMARY KEY,
    solar     boolean NOT NULL
);

-- Pseudonymous: no names, phone numbers or national IDs are stored.
CREATE TABLE mothers (
    mother_id                   serial PRIMARY KEY,
    alias                       text UNIQUE NOT NULL,          -- e.g. M-001
    device_id                   text UNIQUE NOT NULL REFERENCES devices,
    cluster                     text NOT NULL,                 -- migration range: west (Chalbi) / east (Moyale)
    enrolled_at                 timestamptz NOT NULL,
    gestation_weeks_at_enrolment numeric(4,1) NOT NULL,
    anc_visits_done             int NOT NULL DEFAULT 0,
    high_risk                   boolean NOT NULL DEFAULT false
);

CREATE TABLE positions (
    id           bigserial PRIMARY KEY,
    device_id    text NOT NULL REFERENCES devices,
    recorded_at  timestamptz NOT NULL,          -- when the GPS fix was taken (device clock)
    received_at  timestamptz NOT NULL DEFAULT now(),
    lat          double precision NOT NULL,
    lon          double precision NOT NULL,
    battery_pct  real,
    temp_c       real,
    link         text NOT NULL,                 -- 'cell' or 'sat'
    buffered     boolean NOT NULL DEFAULT false, -- delivered late via store-and-forward
    UNIQUE (device_id, recorded_at)              -- makes re-delivery idempotent
);
CREATE INDEX positions_device_time ON positions (device_id, recorded_at DESC);

CREATE TABLE alerts (
    id          bigserial PRIMARY KEY,
    device_id   text NOT NULL REFERENCES devices,
    alert_type  text NOT NULL,      -- LOW_BATTERY | LOST_CONTACT | CROSSED_BORDER | ANC_OVERDUE
    message     text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz
);
-- At most one OPEN alert per device and type -> no alert spam.
CREATE UNIQUE INDEX one_open_alert ON alerts (device_id, alert_type) WHERE resolved_at IS NULL;

-- ---------------------------------------------------------------- helpers
-- "Current time" of the system. With the simulator, time runs faster than real time,
-- so we use the newest fix the server has received. In a real deployment: RETURN now().
CREATE FUNCTION system_now() RETURNS timestamptz
LANGUAGE sql STABLE AS $$
    SELECT COALESCE(max(recorded_at), now()) FROM positions
$$;

CREATE FUNCTION haversine_km(lat1 float8, lon1 float8, lat2 float8, lon2 float8) RETURNS float8
LANGUAGE sql IMMUTABLE AS $$
    SELECT 2 * 6371.0 * asin(sqrt(
        power(sin(radians(lat2 - lat1) / 2), 2) +
        cos(radians(lat1)) * cos(radians(lat2)) * power(sin(radians(lon2 - lon1) / 2), 2)))
$$;

-- North of the border polyline (within its longitude span) = Ethiopia.
CREATE FUNCTION in_ethiopia(p_lat float8, p_lon float8) RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT COALESCE(bool_or(p_lat > a.lat + (b.lat - a.lat) * (p_lon - a.lon) / (b.lon - a.lon)), false)
    FROM border_vertices a
    JOIN border_vertices b ON b.seq = a.seq + 1
    WHERE p_lon >= a.lon AND p_lon < b.lon
$$;

-- Number of antenatal visits that should have happened by this gestational week
-- (4-visit focused ANC schedule: by weeks 16, 28, 32, 36).
CREATE FUNCTION anc_expected(gw numeric) RETURNS int
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN gw >= 36 THEN 4 WHEN gw >= 32 THEN 3
                WHEN gw >= 28 THEN 2 WHEN gw >= 16 THEN 1 ELSE 0 END
$$;

-- ---------------------------------------------------------------- ingestion
-- Device payload: {"d": device_id, "via": "cell"|"sat", "bat": .., "pts": [[iso_ts, lat, lon, bat, temp], ...]}
CREATE FUNCTION ingest_batch(p jsonb) RETURNS int
LANGUAGE plpgsql AS $$
DECLARE n int;
BEGIN
    INSERT INTO positions (device_id, recorded_at, lat, lon, battery_pct, temp_c, link, buffered)
    SELECT p->>'d',
           (pt->>0)::timestamptz, (pt->>1)::float8, (pt->>2)::float8,
           (pt->>3)::real, (pt->>4)::real,
           COALESCE(p->>'via', 'cell'),
           ord < jsonb_array_length(p->'pts')           -- every point except the newest was buffered
    FROM jsonb_array_elements(p->'pts') WITH ORDINALITY AS t(pt, ord)
    ON CONFLICT (device_id, recorded_at) DO NOTHING;
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END $$;

-- Same, but takes base64 text. n8n passes the raw MQTT message as one base64 query
-- parameter: no string concatenation into SQL (no injection) and no comma-splitting issues.
CREATE FUNCTION ingest_batch_b64(b64 text) RETURNS int
LANGUAGE sql AS $$
    SELECT ingest_batch(convert_from(decode(b64, 'base64'), 'UTF8')::jsonb)
$$;

-- ---------------------------------------------------------------- status view
CREATE VIEW latest_status AS
WITH clock AS (SELECT system_now() AS t),
last_fix AS (
    SELECT DISTINCT ON (device_id) device_id, recorded_at, lat, lon, battery_pct, temp_c, link
    FROM positions
    ORDER BY device_id, recorded_at DESC
),
base AS (
    SELECT m.alias, m.device_id, d.solar, m.cluster, m.high_risk, m.anc_visits_done,
           l.recorded_at AS last_fix_at, l.lat, l.lon, l.battery_pct, l.temp_c, l.link AS last_link,
           round((extract(epoch FROM c.t - l.recorded_at) / 3600.0)::numeric, 1) AS hours_since_fix,
           round((m.gestation_weeks_at_enrolment
                  + extract(epoch FROM c.t - m.enrolled_at) / 604800.0)::numeric, 1) AS gestation_weeks,
           in_ethiopia(l.lat, l.lon) AS across_border,
           nb.name AS nearest_base,
           round(nb.km::numeric, 1) AS km_to_base
    FROM mothers m
    JOIN devices d USING (device_id)
    CROSS JOIN clock c
    LEFT JOIN last_fix l USING (device_id)
    LEFT JOIN LATERAL (
        SELECT b.name, haversine_km(l.lat, l.lon, b.lat, b.lon) AS km
        FROM outreach_bases b ORDER BY 2 LIMIT 1
    ) nb ON l.lat IS NOT NULL
),
flags AS (
    SELECT *,
           anc_expected(gestation_weeks) AS anc_expected,
           anc_visits_done < anc_expected(gestation_weeks) AS anc_overdue,
           COALESCE(hours_since_fix > 12, true) AS lost,
           COALESCE(battery_pct < 20, false) AS low_battery
    FROM base
)
SELECT *,
       CASE
           WHEN last_fix_at IS NULL THEN 'no_data'
           WHEN lost AND battery_pct < 10 THEN 'lost_battery'
           WHEN lost THEN 'lost_no_signal'
           WHEN across_border THEN 'across_border'
           WHEN low_battery THEN 'low_battery'
           WHEN anc_overdue THEN 'anc_overdue'
           ELSE 'ok'
       END AS status,
       -- simple outreach priority: who should the mobile team reach first?
       3 * high_risk::int + 2 * anc_overdue::int + 2 * lost::int
         + across_border::int + low_battery::int + (gestation_weeks >= 36)::int AS priority
FROM flags;

-- ---------------------------------------------------------------- alert engine
-- Call periodically (n8n Schedule Trigger). Opens new alerts, resolves cleared ones,
-- and returns ONLY the changes, so n8n just forwards each row to Telegram/SMS.
CREATE FUNCTION evaluate_alerts()
RETURNS TABLE (event text, alias text, alert_type text, message text)
LANGUAGE plpgsql AS $$
#variable_conflict use_column
BEGIN
    -- 1) resolve alerts whose condition is no longer true
    RETURN QUERY
    WITH cleared AS (
        UPDATE alerts a SET resolved_at = now()
        FROM latest_status s
        WHERE a.device_id = s.device_id AND a.resolved_at IS NULL
          AND NOT CASE a.alert_type
                    WHEN 'LOW_BATTERY'    THEN s.low_battery AND NOT s.lost
                    WHEN 'LOST_CONTACT'   THEN s.lost
                    WHEN 'CROSSED_BORDER' THEN s.across_border
                    WHEN 'ANC_OVERDUE'    THEN s.anc_overdue
                  END
        RETURNING a.alert_type, s.alias, s.lat, s.lon
    )
    SELECT 'resolved', c.alias, c.alert_type,
           format('✅ %s resolved: %s — %s (now at %s, %s)', c.alert_type, c.alias,
                  CASE c.alert_type WHEN 'CROSSED_BORDER' THEN 'back in Kenya'
                                    WHEN 'LOST_CONTACT'   THEN 'device back in contact'
                                    ELSE 'condition cleared' END,
                  round(c.lat::numeric, 3), round(c.lon::numeric, 3))
    FROM cleared c;

    -- 2) open new alerts (the partial unique index silently skips already-open ones)
    RETURN QUERY
    WITH candidates AS (
        SELECT s.device_id, s.alias, v.t AS alert_type, v.msg
        FROM latest_status s
        CROSS JOIN LATERAL (VALUES
            ('LOW_BATTERY',    s.low_battery AND NOT s.lost,
             format('🔋 %s battery %s%% (%s) — plan a recharge/swap before it dies. Last fix %s h ago.', s.alias,
                    round(s.battery_pct::numeric), CASE WHEN s.solar THEN 'solar unit' ELSE 'no solar' END,
                    s.hours_since_fix)),
            ('LOST_CONTACT',   s.lost,
             format('📡 %s no contact for %s h — likely %s. Last known: %s, %s (%s km from %s).',
                    s.alias, s.hours_since_fix,
                    CASE WHEN s.battery_pct < 10 THEN 'dead battery' ELSE 'out of coverage' END,
                    round(s.lat::numeric, 3), round(s.lon::numeric, 3), s.km_to_base, s.nearest_base)),
            ('CROSSED_BORDER', s.across_border,
             format('🛂 %s crossed into Ethiopia (%s, %s). Kenyan teams cannot follow — flag for return.',
                    s.alias, round(s.lat::numeric, 3), round(s.lon::numeric, 3))),
            ('ANC_OVERDUE',    s.anc_overdue,
             format('🩺 %s at %s weeks has %s/%s ANC visits%s. %s km from %s.',
                    s.alias, s.gestation_weeks, s.anc_visits_done, s.anc_expected,
                    CASE WHEN s.high_risk THEN ' (HIGH RISK)' ELSE '' END, s.km_to_base, s.nearest_base))
        ) AS v(t, active, msg)
        WHERE v.active AND s.last_fix_at IS NOT NULL
    ),
    opened AS (
        INSERT INTO alerts (device_id, alert_type, message)
        SELECT device_id, alert_type, msg FROM candidates
        ON CONFLICT (device_id, alert_type) WHERE resolved_at IS NULL DO NOTHING
        RETURNING device_id, alert_type, message
    )
    SELECT 'opened', c.alias, o.alert_type, o.message
    FROM opened o JOIN candidates c ON c.device_id = o.device_id AND c.alert_type = o.alert_type;
END $$;
