import sys,unittest,random
from pathlib import Path
from datetime import datetime,timedelta,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'simulator'))
import simulate as s
class SimulatorTests(unittest.TestCase):
 def setUp(self):
  self.f=s.build_fleet(2,42);self.server=s.OfflineServer();self.t=datetime(2026,11,1,tzinfo=timezone.utc)
 def test_delayed_fix_cannot_replace_newer(self):
  m=self.f[0]
  self.server.send(m,'sat',[[self.t.isoformat(),3,38,50,30]])
  self.server.send(m,'cell',[[(self.t-timedelta(hours=1)).isoformat(),2,37,60,30]])
  self.assertEqual(self.server.last[m.device_id][1],3)
 def test_no_data_priority_matches_rules(self):
  m=self.f[0];self.server.send(m,'cell',[[self.t.isoformat(),3,38,50,30]])
  r=s.snapshot(self.f,self.server,self.t)[1]
  r=next(r for r in s.snapshot(self.f,self.server,self.t) if r['alias']==self.f[1].alias)
  self.assertEqual(r['priority'],3*r['high_risk']+2*r['anc_overdue']+2+(r['gestation_weeks']>=36))
 def test_independent_clock_detects_total_outage(self):
  m=self.f[0];self.server.send(m,'cell',[[self.t.isoformat(),3,38,50,30]])
  r=s.snapshot(self.f,self.server,self.t,self.t+timedelta(hours=13))
  self.assertTrue(next(x for x in r if x['alias']==m.alias)['lost'])
 def test_cellular_policy_never_sends_satellite(self):
  m=self.f[0];m.policy='cellular';m.lat=3;m.lon=36;m.rest_left=48
  for h in range(24):s.step(m,self.t+timedelta(hours=h),h,random.Random(h),self.server.send)
  self.assertEqual(self.server.msgs['sat'],0)
 def test_buffer_bound(self):
  m=self.f[0];m.policy='cellular';m.solar=True;m.lat=3;m.lon=36;m.rest_left=500
  for h in range(200):s.step(m,self.t+timedelta(hours=h),h,random.Random(h),self.server.send)
  self.assertLessEqual(len(m.buffer),168)
  self.assertGreater(m.dropped,0)
if __name__=='__main__':unittest.main()
