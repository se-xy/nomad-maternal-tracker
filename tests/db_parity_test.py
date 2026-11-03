#!/usr/bin/env python3
"""
End-to-end check of the database logic.

1. Creates a fresh database, loads db/01_schema.sql + db/02_seed.sql.
2. Runs the simulator for 14 days and feeds every MQTT payload through
   ingest_batch_b64() exactly as n8n does, calling evaluate_alerts() along the way.
3. Compares the latest_status view row-by-row with the simulator's own model
   (status, priority, position, hours since fix) and checks alert dedup.

Usage (needs the `psql` client; the URL must point at a server where you may create databases):
    PGURL=postgresql://nmt:change-me@localhost:5432/postgres python tests/db_parity_test.py
"""
import base64
import json
import os
import random
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "simulator"))
import simulate as sim  # noqa: E402

ADMIN = os.environ.get("PGURL", "postgresql://nmt:change-me@localhost:5432/postgres")
TEST_DB = "nmt_parity_test"
TEST_URL = urlunsplit(urlsplit(ADMIN)._replace(path="/" + TEST_DB))


def psql(url, *args, stdin=None):
    r = subprocess.run(["psql", url, "-v", "ON_ERROR_STOP=1", "-qAt", *args],
                       input=stdin, capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr)
    return r.stdout


def main():
    psql(ADMIN, "-c", f"DROP DATABASE IF EXISTS {TEST_DB}")
    psql(ADMIN, "-c", f"CREATE DATABASE {TEST_DB}")
    try:
        psql(TEST_URL, "-f", str(ROOT / "db/01_schema.sql"), "-f", str(ROOT / "db/02_seed.sql"))

        fleet, rng = sim.build_fleet(30, 42), random.Random(43)
        start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        server, sql = sim.OfflineServer(), []

        def send(m, via, pts):
            server.send(m, via, pts)
            b64 = base64.b64encode(sim.payload(m, via, pts).encode()).decode()
            sql.append(f"SELECT ingest_batch_b64('{b64}');")

        for h in range(14 * 24):
            for m in fleet:
                sim.step(m, start + timedelta(hours=h), h, rng, send)
            if h % 24 == 23:
                sql.append("SELECT count(*) FROM evaluate_alerts();")
        psql(TEST_URL, stdin="\n".join(sql))

        expected = {r["alias"]: r for r in sim.snapshot(fleet, server, start)}
        rows = psql(TEST_URL, "-c", "SELECT alias, status, priority, lat, hours_since_fix FROM latest_status")
        bad = 0
        for line in rows.strip().splitlines():
            alias, status, prio, lat, hrs = line.split("|")
            e = expected[alias]
            if (status, int(prio)) != (e["status"], e["priority"]) or abs(float(lat) - e["lat"]) > 1e-6 \
                    or abs(float(hrs) - e["hours_since_fix"]) > 0.05:
                bad += 1
                print(f"MISMATCH {alias}: db=({status},{prio},{hrs}) model=({e['status']},{e['priority']},{e['hours_since_fix']})")
        dup_open = psql(TEST_URL, "-c", "SELECT count(*) FROM (SELECT device_id, alert_type FROM alerts "
                                        "WHERE resolved_at IS NULL GROUP BY 1,2 HAVING count(*) > 1) x").strip()
        stats = psql(TEST_URL, "-c", "SELECT count(*), count(*) FILTER (WHERE buffered), "
                                     "count(*) FILTER (WHERE link='sat') FROM positions").strip().split("|")
        print(f"{len(sql)} statements ingested -> {stats[0]} stored fixes "
              f"({stats[1]} delivered late via store-and-forward, {stats[2]} via satellite)")
        print(f"status/priority mismatches: {bad}/{len(expected)}   duplicate open alerts: {dup_open}")
        sys.exit(1 if bad or dup_open != "0" else 0)
    finally:
        psql(ADMIN, "-c", f"DROP DATABASE IF EXISTS {TEST_DB}")


if __name__ == "__main__":
    main()
