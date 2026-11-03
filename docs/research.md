# Communication policy experiment

All results below are synthetic simulation outputs. No field deployment or health benefit has been measured.

## Question

What energy–freshness trade-off results from adapting satellite transmissions to movement and battery level?

## Method

30 seeds, 30 devices, 14 days, fixed start 2026-11-01 UTC. Nine conditions per seed (270 trials): three communication policies, matched all-solar/all-non-solar conditions, satellite success sensitivity (50%, 100%), and buffer sensitivity (48, 336 fixes). Baseline satellite success is 85% and buffer capacity 168 fixes.

The adaptive rule transmits outside coverage after six hours when movement since the previous successful satellite fix is at least 3 km and battery is at least 20%; otherwise it waits twelve hours. It does not use clinical risk to change transmission. Cellular upload behaviour is unchanged.

Each device-hour uses the same seeded environmental random stream across policies. This keeps movement, weather and kiosk draws matched; strategy-dependent satellite draws cannot change later environmental draws. The original demo uses a different random-stream design, so these totals should not be compared directly to its single-seed README totals.

## Baseline results: mean across 30 seeds

| Policy | Device uptime % | Mean location age, h | Stale/unknown device-hours % | Satellite attempts |
|---|---:|---:|---:|---:|
| cellular | 85.71 | 51.45 | 63.44 | 0.00 |
| fixed | 81.80 | 19.61 | 18.04 | 860.13 |
| adaptive | 83.10 | 19.86 | 20.79 | 583.30 |

Stale means older than 12 hours. Unknown device-hours are included in stale/unknown; location-age averages exclude hours before the first fix. Satellite attempts count powered devices attempting an uplink, including failed attempts. Buffer evictions are not necessarily unique lost fixes: some evicted points were already sent by satellite.

## Paired uncertainty estimates

Adaptive minus fixed, bootstrap 95% percentile intervals over 30 paired seeds (5,000 resamples, seed 2026). These reflect simulation variability, not uncertainty about whether the model represents reality.

| Metric | Mean difference | 95% interval |
|---|---:|---|
| uptime_pct | 1.30 | 1.24 to 1.35 |
| mean_age_h | 0.25 | 0.07 to 0.43 |
| stale_or_unknown_pct | 2.74 | 2.46 to 3.01 |
| satellite_attempts | -276.83 | -286.00 to -267.13 |

## Interpretation

Adaptive transmission trades fewer satellite attempts and improved uptime for more stale/unknown device-hours in this model. It is not a universal improvement. The fixed hybrid policy offers better freshness, while cellular-only saves transmission energy but leaves much longer gaps. A deployment would need a stakeholder-defined freshness requirement before choosing a policy.

## Limitations

- Approximate geography, circular coverage areas and straight-line movement.
- Battery drain, charging and satellite success are assumptions, not calibrated measurements.
- No satellite fees, radio protocol overhead, terrain constraints or real health outcomes are modelled.
- The model records successful publications immediately; infrastructure outages are covered separately by integration tests.
- Confidence intervals do not establish clinical benefit or deployment safety.
- The rule was not tuned using these results; further tuning requires held-out seeds and scenarios.

## Reproduce

```sh
python experiments/run.py --seeds 30
python experiments/summarise.py
python -m unittest discover -s tests -p "test_*.py"
```

Raw trials: [results.csv](../experiments/results.csv). Experiment source: [run.py](../experiments/run.py).
