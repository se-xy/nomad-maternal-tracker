#!/usr/bin/env python3
"""
Nomad Maternal Tracker: desert-aware GPS tracker simulator.

Simulates bracelet trackers worn by pregnant women in pastoralist households in
Marsabit County, northern Kenya, and publishes their data over MQTT the way a
real low-power device would.

What it models (all parameters in P below):
  * Movement between water points / grazing areas in two migration ranges
    (west: Chalbi desert, east: Moyale), walking only in daylight, resting for days.
  * Occasional trips across the Ethiopian border (east range only).
  * Cell coverage only near towns. Outside coverage the device stores fixes in
    flash (store-and-forward) and uploads the whole backlog when it reaches signal.
  * A low-bandwidth satellite heartbeat (latest position only) every few hours
    when out of coverage, which can fail.
  * Battery drain that increases with heat, extra drain while searching for
    network, and daytime solar charging (half the fleet), reduced by panel dust.
  * Non-solar devices recharged only at a charging kiosk in towns.

Modes:
  python simulate.py --write-sql     -> regenerate db/02_seed.sql (devices, mothers, geography)
  python simulate.py --dry-run       -> run offline, print model statistics, write dashboard/demo-data.json
  python simulate.py                 -> publish live to MQTT (default localhost:1883)
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGION = json.loads((ROOT / "geo" / "region.json").read_text())
EAT = timedelta(hours=3)  # East Africa Time, for daylight logic

# --------------------------------------------------------------------------- model parameters
P = dict(
    walk_kmh=3.0,            # walking speed with livestock, daylight only
    rest_hours=(24, 120),    # time spent at a water point / settlement
    settle_jitter_km=2.0,    # spread of a settlement around a waypoint
    border_trip_prob=0.15,   # east range: chance the next destination is across the border
    fix_interval_h=1,        # one GPS fix per simulated hour
    base_drain=0.35,         # %/h for GPS fix + MCU at 30 °C
    heat_threshold_c=30.0,
    heat_coeff=0.05,         # +5 % drain per °C above threshold
    cell_cost=0.15,          # %/h when uploading over cellular
    search_cost=0.10,        # %/h modem searching for a network outside coverage
    sat_cost=1.0,            # % per satellite transmission
    sat_every_h=6,           # satellite heartbeat interval outside coverage
    sat_success=0.85,        # satellite uplink success probability
    solar_max=3.0,           # %/h charge at solar noon with a clean panel
    kiosk_prob=0.03,         # per daylight hour in town: non-solar device gets recharged
    buffer_max=168,          # flash buffer: 7 days of hourly fixes
    low_battery=20.0,        # % (must match db view)
    lost_after_h=12.0,       # h without contact (must match db view)
)


# --------------------------------------------------------------------------- geometry
def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def offset(lat, lon, dx_km, dy_km):
    return lat + dy_km / 110.574, lon + dx_km / (111.320 * math.cos(math.radians(lat)))


def in_ethiopia(lat, lon):
    b = REGION["border"]
    for (lon1, lat1), (lon2, lat2) in zip(b, b[1:]):
        if lon1 <= lon < lon2:
            return lat > lat1 + (lat2 - lat1) * (lon - lon1) / (lon2 - lon1)
    return False


def in_coverage(lat, lon):
    return any(haversine_km(lat, lon, c["lat"], c["lon"]) <= c["radius_km"] for c in REGION["cell_coverage"])


def nearest_base(lat, lon):
    return min(((b["name"], haversine_km(lat, lon, b["lat"], b["lon"])) for b in REGION["outreach_bases"]),
               key=lambda x: x[1])


def temperature(local_hour, rng):
    """Arid-lowland daily cycle: ~23 °C before dawn, ~39 °C mid-afternoon."""
    return 31 + 8 * math.sin(2 * math.pi * (local_hour - 9) / 24) + rng.gauss(0, 1.0)


def anc_expected(gw):
    return 4 if gw >= 36 else 3 if gw >= 32 else 2 if gw >= 28 else 1 if gw >= 16 else 0


# --------------------------------------------------------------------------- fleet
@dataclass
class Mother:
    alias: str
    device_id: str
    cluster: str
    solar: bool
    panel_eff: float
    lat: float
    lon: float
    battery: float
    gestation_at_enrol: float
    enrolled_days_ago: int
    anc_done: int
    high_risk: bool
    target: dict | None = None
    rest_left: int = 0
    alive: bool = True
    buffer: list = field(default_factory=list)
    # stats
    hours_alive: int = 0
    hours_in_cov: int = 0
    fixes: int = 0
    dropped: int = 0


def build_fleet(n, seed):
    rng = random.Random(seed)
    fleet = []
    for i in range(n):
        cluster = "west" if i % 2 == 0 else "east"
        home = rng.choice([w for w in REGION["waypoints"][cluster] if not w.get("cross_border")])
        lat, lon = offset(home["lat"], home["lon"], rng.uniform(-2, 2), rng.uniform(-2, 2))
        gw = round(rng.uniform(8, 30), 1)
        days = rng.randint(0, 28)
        fleet.append(Mother(
            alias=f"M-{i + 1:03d}", device_id=f"NMT-{i + 1:03d}", cluster=cluster,
            solar=(i // 2) % 2 == 0,                     # half of each range has solar
            panel_eff=round(rng.uniform(0.6, 1.0), 2),   # dust on panel
            lat=lat, lon=lon, battery=round(rng.uniform(40, 100), 1),
            gestation_at_enrol=gw, enrolled_days_ago=days,
            anc_done=rng.randint(0, anc_expected(gw)), high_risk=rng.random() < 0.2,
            rest_left=rng.randint(0, 48),
        ))
    return fleet


# --------------------------------------------------------------------------- simulation step
def step(m: Mother, t: datetime, hour_idx: int, rng: random.Random, send):
    local_h = (t + EAT).hour
    daylight = 6 <= local_h < 18
    temp = temperature(local_h, rng)

    # --- movement
    if m.target is None and m.rest_left <= 0:
        options = [w for w in REGION["waypoints"][m.cluster] if not w.get("cross_border")]
        cross = [w for w in REGION["waypoints"][m.cluster] if w.get("cross_border")]
        m.target = rng.choice(cross) if cross and rng.random() < P["border_trip_prob"] else rng.choice(options)
    if m.rest_left > 0:
        m.rest_left -= 1
    elif m.target and daylight:
        d = haversine_km(m.lat, m.lon, m.target["lat"], m.target["lon"])
        step_km = P["walk_kmh"] * rng.uniform(0.7, 1.2)
        if d <= step_km:
            j = P["settle_jitter_km"]
            m.lat, m.lon = offset(m.target["lat"], m.target["lon"], rng.uniform(-j, j), rng.uniform(-j, j))
            m.target, m.rest_left = None, rng.randint(*P["rest_hours"])
        else:
            f = step_km / d
            m.lat += (m.target["lat"] - m.lat) * f
            m.lon += (m.target["lon"] - m.lon) * f

    cov = in_coverage(m.lat, m.lon)
    sat_slot = (not cov) and hour_idx % P["sat_every_h"] == 0

    # --- energy
    charge = 0.0
    if m.solar and daylight:
        charge = P["solar_max"] * math.sin(math.pi * (local_h - 6) / 12) * m.panel_eff
    if not m.solar and cov and daylight and rng.random() < P["kiosk_prob"]:
        charge = 100.0
    if m.alive:
        heat = 1 + max(0.0, temp - P["heat_threshold_c"]) * P["heat_coeff"]
        drain = P["base_drain"] * heat + (P["cell_cost"] if cov else P["search_cost"])
        if sat_slot:
            drain += P["sat_cost"]
        m.battery = min(100.0, m.battery - drain + charge)
        if m.battery <= 0:
            m.battery, m.alive = 0.0, False
    else:
        m.battery = min(100.0, m.battery + charge)
        if m.battery >= 5:          # brown-out recovery threshold
            m.alive = True
    if not m.alive:
        return

    # --- fix + transmit
    m.hours_alive += 1
    m.hours_in_cov += cov
    m.fixes += 1
    m.buffer.append([t.strftime("%Y-%m-%dT%H:%M:%SZ"), round(m.lat, 5), round(m.lon, 5),
                     round(m.battery, 1), round(temp, 1)])
    if len(m.buffer) > P["buffer_max"]:
        m.buffer.pop(0)
        m.dropped += 1
    if cov:
        send(m, "cell", m.buffer)
        m.buffer = []
    elif sat_slot and rng.random() < P["sat_success"]:
        send(m, "sat", m.buffer[-1:])   # heartbeat only; backlog stays in flash


def payload(m, via, pts):
    return json.dumps({"d": m.device_id, "via": via, "bat": round(m.battery, 1),
                       "sol": m.solar, "pts": pts}, separators=(",", ":"))


# --------------------------------------------------------------------------- server-side mirror (dry run)
class OfflineServer:
    """Keeps what the backend would know, to build the demo snapshot and stats."""
    def __init__(self):
        self.last = {}           # device_id -> latest point received
        self.msgs = {"cell": 0, "sat": 0}
        self.bytes = 0
        self.points = 0

    def send(self, m, via, pts):
        body = payload(m, via, pts)
        self.msgs[via] += 1
        self.bytes += len(body)
        self.points += len(pts)
        newest = pts[-1]
        if m.device_id not in self.last or newest[0] > self.last[m.device_id][0]:
            self.last[m.device_id] = newest + [via]


def snapshot(fleet, server: OfflineServer, sim_start):
    """Same columns and rules as the latest_status view in db/01_schema.sql."""
    if not server.last:
        return []
    now = max(datetime.fromisoformat(p[0].replace("Z", "+00:00")) for p in server.last.values())
    rows = []
    for m in fleet:
        enrolled = sim_start - timedelta(days=m.enrolled_days_ago)
        gw = round(m.gestation_at_enrol + (now - enrolled).total_seconds() / 604800, 1)
        exp = anc_expected(gw)
        p = server.last.get(m.device_id)
        row = dict(alias=m.alias, device_id=m.device_id, solar=m.solar, cluster=m.cluster,
                   high_risk=m.high_risk, anc_visits_done=m.anc_done, gestation_weeks=gw,
                   anc_expected=exp, anc_overdue=m.anc_done < exp)
        if p is None:
            row.update(status="no_data", lost=True, low_battery=False, across_border=False,
                       last_fix_at=None, lat=None, lon=None, priority=0)
            rows.append(row)
            continue
        ts = datetime.fromisoformat(p[0].replace("Z", "+00:00"))
        hrs = round((now - ts).total_seconds() / 3600, 1)
        lost, low, across = hrs > P["lost_after_h"], p[3] < P["low_battery"], in_ethiopia(p[1], p[2])
        base, km = nearest_base(p[1], p[2])
        status = ("lost_battery" if lost and p[3] < 10 else "lost_no_signal" if lost else
                  "across_border" if across else "low_battery" if low else
                  "anc_overdue" if row["anc_overdue"] else "ok")
        row.update(last_fix_at=p[0], lat=p[1], lon=p[2], battery_pct=p[3], temp_c=p[4], last_link=p[5],
                   hours_since_fix=hrs, across_border=across, nearest_base=base, km_to_base=round(km, 1),
                   lost=lost, low_battery=low, status=status,
                   priority=3 * m.high_risk + 2 * row["anc_overdue"] + 2 * lost + across + low + (gw >= 36))
        rows.append(row)
    return sorted(rows, key=lambda r: -r["priority"])


def print_stats(fleet, server, hours):
    def group(sel):
        g = [m for m in fleet if sel(m)]
        up = sum(m.hours_alive for m in g) / (len(g) * hours) * 100
        cov = sum(m.hours_in_cov for m in g) / max(1, sum(m.hours_alive for m in g)) * 100
        return len(g), up, cov
    print(f"\nSimulated {hours} h ({hours / 24:.0f} days), {len(fleet)} devices")
    for name, sel in [("solar", lambda m: m.solar), ("no solar", lambda m: not m.solar),
                      ("west / Chalbi", lambda m: m.cluster == "west"), ("east / Moyale", lambda m: m.cluster == "east")]:
        n, up, cov = group(sel)
        print(f"  {name:14s} n={n:2d}  device uptime {up:5.1f}%   time in cell coverage {cov:5.1f}%")
    fixes = sum(m.fixes for m in fleet)
    print(f"  messages: {server.msgs['cell']} cellular batches, {server.msgs['sat']} satellite heartbeats, "
          f"{server.bytes / 1024:.0f} KiB total")
    print(f"  fixes recorded {fixes}, points uploaded {server.points}, dropped from full buffer "
          f"{sum(m.dropped for m in fleet)}")


# --------------------------------------------------------------------------- seed SQL
def write_sql(fleet, path: Path):
    q = lambda s: "'" + str(s).replace("'", "''") + "'"
    lines = ["-- GENERATED by simulator/simulate.py --write-sql. Do not edit by hand.", ""]
    lines.append("INSERT INTO outreach_bases (name, lat, lon) VALUES")
    lines.append(",\n".join(f"  ({q(b['name'])}, {b['lat']}, {b['lon']})" for b in REGION["outreach_bases"]) + ";\n")
    lines.append("INSERT INTO border_vertices (seq, lon, lat) VALUES")
    lines.append(",\n".join(f"  ({i}, {lon}, {lat})" for i, (lon, lat) in enumerate(REGION["border"], 1)) + ";\n")
    lines.append("INSERT INTO devices (device_id, solar) VALUES")
    lines.append(",\n".join(f"  ({q(m.device_id)}, {str(m.solar).lower()})" for m in fleet) + ";\n")
    lines.append("INSERT INTO mothers (alias, device_id, cluster, enrolled_at, gestation_weeks_at_enrolment, "
                 "anc_visits_done, high_risk) VALUES")
    lines.append(",\n".join(
        f"  ({q(m.alias)}, {q(m.device_id)}, {q(m.cluster)}, now() - interval '{m.enrolled_days_ago} days', "
        f"{m.gestation_at_enrol}, {m.anc_done}, {str(m.high_risk).lower()})" for m in fleet) + ";")
    path.write_text("\n".join(lines) + "\n")
    print(f"wrote {path.relative_to(ROOT)}")


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mothers", type=int, default=30)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--days", type=float, default=14)
    ap.add_argument("--speed", type=float, default=1.0, help="real seconds per simulated hour (live mode)")
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--write-sql", action="store_true")
    ap.add_argument("--snapshot", default=str(ROOT / "dashboard" / "demo-data.json"))
    ap.add_argument("--start", help="simulation start, ISO UTC (default: now; dry-run: 2026-11-01)")
    a = ap.parse_args()

    fleet = build_fleet(a.mothers, a.seed)
    if a.write_sql:
        write_sql(fleet, ROOT / "db" / "02_seed.sql")
        return

    rng = random.Random(a.seed + 1)
    if a.start:
        start = datetime.fromisoformat(a.start.replace("Z", "+00:00"))
    elif a.dry_run:
        start = datetime(2026, 11, 1, tzinfo=timezone.utc)   # fixed, so dry-run statistics are reproducible
    else:
        start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    hours = int(a.days * 24)

    if a.dry_run:
        server = OfflineServer()
        for h in range(hours):
            for m in fleet:
                step(m, start + timedelta(hours=h), h, rng, server.send)
        print_stats(fleet, server, hours)
        Path(a.snapshot).write_text(json.dumps(snapshot(fleet, server, start), indent=1, default=str))
        print(f"  snapshot -> {Path(a.snapshot).relative_to(ROOT) if Path(a.snapshot).is_relative_to(ROOT) else a.snapshot}")
        return

    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        sys.exit("pip install -r simulator/requirements.txt")
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="nmt-simulator")
    client.connect(a.broker, a.port)
    client.loop_start()

    def send(m, via, pts):
        client.publish(f"nmt/tracker/{m.device_id}/batch", payload(m, via, pts), qos=1)

    print(f"publishing {a.mothers} devices to {a.broker}:{a.port}, 1 simulated hour = {a.speed}s")
    try:
        for h in range(hours):
            t = start + timedelta(hours=h)
            for m in fleet:
                step(m, t, h, rng, send)
            if h % 24 == 0:
                alive = sum(m.alive for m in fleet)
                print(f"[{t:%Y-%m-%d %H:%M}Z] day {h // 24 + 1}: {alive}/{len(fleet)} devices powered")
            time.sleep(a.speed)
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
