import unittest
from datetime import date
from collect_history_instantaneous import parse,collect,audit,periods
class Tests(unittest.TestCase):
 def fixture(self):
  return {'value':{'timeSeries':[{'sourceInfo':{'siteCode':[{'value':'08378500'}]},'variable':{'variableCode':[{'value':'00060'}]},'values':[{'value':[{'value':'500','dateTime':'2026-11-01T01:15:00-06:00','qualifiers':['P']},{'value':'510','dateTime':'2026-11-01T01:30:00-06:00','qualifiers':['P']}]}]}]}}
 def test_parse(self):
  r=parse(self.fixture());self.assertEqual(len(r),2);self.assertEqual(r[0]['timestamp_utc'],'2026-11-01T07:15:00Z');self.assertEqual(r[0]['discharge_cfs'],500)
 def test_dedupe(self):
  rows=collect(date(2026,11,1),date(2026,11,1),lambda url:self.fixture());self.assertEqual(len(rows),2)
  self.assertEqual(audit(rows,date(2026,11,1),date(2026,11,1))['sites']['dalton']['interval_minutes_counts'],{15.0:1})
 def test_chunks(self):
  self.assertEqual(list(periods(date(2026,10,1),date(2026,11,2))),[(date(2026,10,1),date(2026,10,14)),(date(2026,10,15),date(2026,10,28)),(date(2026,10,29),date(2026,11,2))])
if __name__=='__main__':unittest.main()
