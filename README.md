# Nomad Maternal Tracker

**A tracking and alerting system for mobile antenatal care among nomadic pastoralist communities in arid northern Kenya.**
Prototype v0.1 with simulated devices and synthetic data.

![Outreach dashboard](docs/dashboard.png)

**Live demo (synthetic data):** open `dashboard/index.html?demo=1` through GitHub Pages or any static server.

---

## Why

In Marsabit County (about 66,000 km², largely desert and semi-desert), many families are nomadic pastoralists who move between water points and grazing land. Pregnant women often miss the recommended antenatal care (ANC) visits because the nearest dispensary may be days away, and the family has already moved on by the next visit.

A pilot in Moyale sub-county, led by epidemiologist Dahabo Adi, turned the model around: expectant mothers wore GPS trackers hidden in traditional beaded bracelets, and mobile clinical teams drove to wherever the women were. The pilot reported three problems that limit this approach: **dead batteries** make mothers disappear from the system, **families cross into Ethiopia** where Kenyan teams cannot follow, and the system needs to **scale beyond the pilot**. ([source video](https://www.youtube.com/watch?v=CKkGJWm68pc))

This project is an independent, open-source software reimplementation of that idea. It does not cover the hardware. The focus is on the problems above, under realistic desert conditions.

## What it does

* **Simulates** bracelet trackers for 30 mothers moving through two migration ranges (Chalbi desert and the Moyale area), including heat, sparse network coverage and border crossings.
* **Ingests** device data over MQTT. Points recorded offline arrive late via store-and-forward and are merged idempotently.
* **Decides** each mother's status in SQL: lost (dead battery vs. out of coverage), across the border, low battery, ANC overdue. It also ranks mothers by **outreach priority**.
* **Alerts** field teams on Telegram only when something *changes*, including "back in Kenya" and "back in contact" messages.
* **Shows** a map for the outreach team with a prioritised list, last-known positions, coverage zones and the nearest base.

## Designed for the region, not just placed on a map

| Constraint in northern Kenya | Design decision |
|---|---|
| Cellular signal only near a few towns | **Store-and-forward**: the device keeps up to 7 days of hourly fixes in flash and uploads the backlog when it reaches a tower |
| Large areas with no signal at all | **Satellite heartbeat** every 6 h (latest position only, 85% success) so the team still knows roughly where a mother is |
| Desert heat (~23 °C night, ~39 °C afternoon) shortens battery life | Battery drain increases by 5% per °C above 30 °C; modem network-search cost is modelled |
| Strong sun all year | **Solar charging** for half the fleet, reduced by panel dust (60–100% efficiency) |
| Dead battery and no signal look identical (silence) | `LOST_CONTACT` alerts say which one is *likely*, based on the last reported battery level |
| Families cross into Ethiopia near Moyale | Border geofence: `CROSSED_BORDER` alert, then a "back in Kenya" alert so a team can meet her |
| Long distances, few roads | Distance to the nearest outreach base in every alert, plus a priority score for planning the day's route |
| Duplicate delivery (satellite + later cellular batch) | `UNIQUE (device_id, recorded_at)` makes ingestion idempotent |

## Architecture

```mermaid
flowchart LR
    T["Bracelet trackers<br/>simulator/simulate.py"] -- "MQTT batch<br/>(cellular, store-and-forward)" --> B[(Mosquitto)]
    T -. "satellite heartbeat" .-> B
    B --> I["n8n: Ingest"]
    I -- "ingest_batch_b64()" --> DB[("PostgreSQL<br/>positions · mothers · alerts")]
    A["n8n: Alerts<br/>every 1 min"] -- "evaluate_alerts()" --> DB
    A --> TG["Telegram<br/>(SMS on roadmap)"]
    W["n8n: API webhook"] -- "latest_status view" --> DB
    D["Leaflet dashboard"] -- "/api/latest" --> N[nginx] --> W
```

All decision logic (status, priority, alert opening/resolving) lives in **PostgreSQL** (`db/01_schema.sql`). The n8n workflows are thin: one trigger, one SQL call, one output. This keeps the logic testable and version-controlled. In this prototype the satellite path goes through the same broker; a real deployment would receive it from the satellite provider's API.

## What the simulation shows

`python simulator/simulate.py --dry-run` (14 days, 30 devices, seed 42, reproducible):

| | Device uptime | Time in cell coverage |
|---|---|---|
| Solar bracelets (16) | **100%** | 33% |
| Non-solar bracelets (14) | **53%** | 44% |

* Without solar, a device is dead about half the time, even with recharging at town kiosks. This supports the original project's goal of moving to solar-powered units.
* Data volume: 2,878 cellular batches + 719 satellite heartbeats ≈ **1.2 KiB per device per day**. Connectivity cost is small; coverage is the real problem.
* 639 fixes were lost because solar devices stayed out of coverage for more than 7 days and the buffer overflowed. This is a concrete argument for a larger flash buffer or a satellite *batch* option.
* In a typical run about one third of stored fixes arrive late via store-and-forward. Without that design they would be lost.

> These figures come from my model's assumptions (listed in `simulator/simulate.py`, `P` dict), not from field data. They show how the design behaves; they do not measure the real world.

## Quick start

Requirements: Docker + Docker Compose, Python 3.10+.

```bash
cp .env.example .env                      # set POSTGRES_PASSWORD
docker compose up -d                      # Mosquitto, Postgres (auto-loads db/*.sql), n8n, dashboard
# build and activate the three n8n workflows: see workflows/README.md (≈20 min)
pip install -r simulator/requirements.txt
python simulator/simulate.py --speed 1    # 1 simulated hour per second; 14 days ≈ 6 min
```

* Dashboard: http://localhost:8080 (falls back to demo data if the API is not up)
* n8n: http://localhost:5678

Other modes:

```bash
python simulator/simulate.py --dry-run     # offline run: prints statistics, writes dashboard/demo-data.json
python simulator/simulate.py --write-sql   # regenerate db/02_seed.sql from geo/region.json (+ --mothers/--seed)
```

## Testing

`tests/db_parity_test.py` builds a fresh database, replays a 14-day simulation through `ingest_batch_b64()` exactly as n8n does, runs the alert engine daily, and checks that:

* the SQL `latest_status` view matches the simulator's own model for every mother (status, priority, position, time since last fix), and
* no mother ever has two open alerts of the same type.

```bash
PGURL=postgresql://nmt:<password>@localhost:5432/postgres python tests/db_parity_test.py
# 3820 statements ingested -> 5831 stored fixes (2025 delivered late via store-and-forward, 738 via satellite)
# status/priority mismatches: 0/30   duplicate open alerts: 0
```

## Repository layout

```
docker-compose.yml     Mosquitto · Postgres · n8n · nginx
geo/region.json        bases, coverage zones, waypoints, border line (single source of truth)
simulator/             device simulator (MQTT, dry-run, seed generator)
db/                    schema + logic (01), generated seed data (02)
workflows/             n8n build guide + exported workflow JSON
dashboard/             single-file Leaflet map + demo data
tests/                 end-to-end database test
```

## Privacy and ethics

The real version of this system would hold the **live location of pregnant women from a marginalised community**. Under Kenya's Data Protection Act (2019), health data is sensitive personal data. This prototype:

* uses **synthetic data only**; no real person is represented;
* stores mothers under **pseudonyms** (`M-001`) with no names, phone numbers or ID numbers;
* keeps location tables separate from identity, so access can be restricted per role.

A real deployment would also need: informed consent in the local language (and the right to remove the bracelet at any time), encryption in transit (MQTT over TLS) and at rest, per-device credentials, role-based access, retention limits on location history, and agreement with county health authorities. Location data like this could put people at risk if leaked, so the threat model matters as much as the features.

## Limitations

* Coordinates, coverage radii and the border line are **approximate** and hand-entered.
* Movement is a simple waypoint model, not based on real migration data.
* ANC visits are seeded, not recorded; the schedule uses the 4-visit model mentioned in the pilot (WHO's 2016 guidance recommends at least 8 contacts).
* MQTT and n8n run without authentication (local demo only).

## Roadmap

- [ ] Record ANC visits from the field (form or USSD) and the postnatal phase (newborn vaccination follow-up)
- [ ] SMS alerts via Africa's Talking for teams without smartphones
- [ ] Clustering of movement history (DBSCAN) to suggest **pop-up clinic locations**
- [ ] Daily outreach route planning (OSRM / OR-Tools) by priority and distance
- [ ] Official boundary data and real coverage maps
- [ ] TLS + per-device credentials on the broker; role-based access on the API
- [ ] Configurable ANC schedule (4-visit vs. WHO 8-contact model)

## Acknowledgement

Inspired by the maternal GPS-tracking pilot in Moyale, Marsabit County, led by Dahabo Adi. This repository is an independent learning project and is not affiliated with that initiative.

## Author

**Peter Robia Mwaniki**, BSc Computer Science, University of Dunaújváros.
Licensed under the MIT License.
