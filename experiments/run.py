#!/usr/bin/env python3
"""Matched simulation experiments. Output measures model behaviour, not clinical outcomes."""
import argparse,csv,json,random,statistics,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"simulator"))
import simulate as s

def run(seed,policy,days=14,solar=None,sat_success=.85,buffer_max=168):
    fleet=s.build_fleet(30,seed)
    for m in fleet:
        m.policy=policy
        if solar is not None: m.solar=solar
    start=datetime(2026,11,1,tzinfo=timezone.utc)
    server=s.OfflineServer();ages=[];unknown=0;unique=set();attempts=[0]
    original=dict(s.P);s.P.update(sat_success=sat_success,buffer_max=buffer_max)
    def send(m,via,pts):
        server.send(m,via,pts)
        unique.update((m.device_id,p[0]) for p in pts)
    try:
        for h in range(days*24):
            t=start+timedelta(hours=h)
            for i,m in enumerate(fleet):
                # Reset per device-hour: strategy-dependent random draws cannot alter
                # later movement/weather/charging. The satellite draw occurs last.
                rng=random.Random(seed*100000000+h*1000+i)
                s.step(m,t,h,rng,send)
                if m.last_sat_hour==h: attempts[0]+=1
                p=server.last.get(m.device_id)
                if p:
                    age=(t-datetime.fromisoformat(p[0].replace("Z","+00:00"))).total_seconds()/3600
                    ages.append(age)
                else: unknown+=1
    finally:
        s.P.clear();s.P.update(original)
    total=days*24*len(fleet)
    return dict(seed=seed,policy=policy,days=days,solar="mixed" if solar is None else str(solar),sat_success=sat_success,buffer_max=buffer_max,
        uptime_pct=100*sum(m.hours_alive for m in fleet)/total,
        mean_age_h=statistics.mean(ages) if ages else None,
        p95_age_h=sorted(ages)[min(len(ages)-1,int(.95*len(ages)))] if ages else None,
        stale_or_unknown_pct=100*(sum(a>12 for a in ages)+unknown)/total,
        unknown_pct=100*unknown/total,satellite_attempts=attempts[0],satellite_delivered=server.msgs["sat"],
        cellular_batches=server.msgs["cell"],unique_delivered_fixes=len(unique),
        recorded_fixes=sum(m.fixes for m in fleet),buffer_evictions=sum(m.dropped for m in fleet),payload_bytes=server.bytes)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--seeds",type=int,default=30);ap.add_argument("--output",default=str(ROOT/"experiments/results.csv"));a=ap.parse_args()
    rows=[]
    for seed in range(a.seeds):
        for policy in ("cellular","fixed","adaptive"):
            rows.append(run(seed,policy))
        for solar in (False,True): rows.append(run(seed,"fixed",solar=solar))
        for success in (.5,1.): rows.append(run(seed,"adaptive",sat_success=success))
        for buffer in (48,336): rows.append(run(seed,"adaptive",buffer_max=buffer))
    path=Path(a.output);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w") as f:
        w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
    print(f"Wrote {len(rows)} trials to {path}")
if __name__=="__main__":main()
