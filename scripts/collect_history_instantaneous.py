#!/usr/bin/env python3
"""Download native-resolution USGS discharge observations for the Pecos study.
Does not modify the existing daily weather/flow collector or dashboard.
Usage: python collect_history_instantaneous.py --start 2026-11-01 --end 2026-11-10
Dates are inclusive in America/Denver; timestamps are stored in UTC.
"""
import argparse, csv, json, time, urllib.parse, urllib.request
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from collections import Counter

STATIONS = {'dalton':'08378500', 'rio_mora':'08377900'}
API = 'https://waterservices.usgs.gov/nwis/iv/'
FIELDS = ['site','site_id','timestamp_utc','timestamp_local','discharge_cfs','qualifiers']

def fetch(url):
    req=urllib.request.Request(url,headers={'User-Agent':'PecosWatershedHistoricalResearch/1.0','Accept':'application/json'})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req,timeout=120) as response:
                return json.load(response)
        except Exception:
            if attempt==3: raise
            time.sleep(2**attempt)

def periods(start,end,days=14):
    cur=start
    while cur<=end:
        last=min(end,cur+timedelta(days=days-1))
        yield cur,last
        cur=last+timedelta(days=1)

def parse(payload):
    records=[]
    for ts in payload.get('value',{}).get('timeSeries',[]):
        site=ts.get('sourceInfo',{}).get('siteCode',[{}])[0].get('value')
        name=next((n for n,s in STATIONS.items() if s==site),None)
        parameter=ts.get('variable',{}).get('variableCode',[{}])[0].get('value')
        if not name or parameter!='00060':continue
        for block in ts.get('values',[]):
            for v in block.get('value',[]):
                try:
                    q=float(v['value']); dt=datetime.fromisoformat(v['dateTime'])
                    if q<0 or dt.tzinfo is None:continue
                except (ValueError,TypeError,KeyError):continue
                utc=dt.astimezone(timezone.utc)
                records.append({'site':name,'site_id':site,'timestamp_utc':utc.isoformat().replace('+00:00','Z'),
                    'timestamp_local':utc.astimezone(ZoneInfo('America/Denver')).isoformat(),
                    'discharge_cfs':q,'qualifiers':';'.join(v.get('qualifiers',[]))})
    return records

def collect(start,end,fetcher=fetch):
    found={}
    for first,last in periods(start,end):
        params={'format':'json','sites':','.join(STATIONS.values()),'parameterCd':'00060',
            'startDT':first.isoformat(),'endDT':last.isoformat(),'siteStatus':'all'}
        url=API+'?'+urllib.parse.urlencode(params)
        for r in parse(fetcher(url)):
            key=(r['site_id'],r['timestamp_utc'])
            if key in found and found[key]['discharge_cfs']!=r['discharge_cfs']:
                raise ValueError(f'Conflicting duplicate observation: {key}')
            found[key]=r
    return sorted(found.values(),key=lambda r:(r['timestamp_utc'],r['site_id']))

def audit(rows,start,end):
    per_site={}
    for name,site_id in STATIONS.items():
        r=sorted((x for x in rows if x['site']==name),key=lambda x:x['timestamp_utc'])
        stamps=[datetime.fromisoformat(x['timestamp_utc'].replace('Z','+00:00')) for x in r]
        intervals=Counter(round((b-a).total_seconds()/60,3) for a,b in zip(stamps,stamps[1:]))
        per_site[name]={'site_id':site_id,'records':len(r),'first_utc':r[0]['timestamp_utc'] if r else None,
            'last_utc':r[-1]['timestamp_utc'] if r else None,'interval_minutes_counts':dict(sorted(intervals.items())),
            'qualifiers':dict(Counter(x['qualifiers'] for x in r)),
            'gaps_over_15_minutes':sum(1 for v in intervals.elements() if v>15)}
    return {'requested_start_local':start.isoformat(),'requested_end_local_inclusive':end.isoformat(),
        'source':API,'parameter_code':'00060','units':'ft3/s','timezone_output':'UTC and America/Denver',
        'records':len(rows),'sites':per_site,
        'notes':['Native observations are retained; no interpolation or resampling.','Cadence is inferred from returned timestamps; 15 minutes is not assumed.',
                 'Site-specific missing records, flags, and DST offsets must be inspected before modeling.',
                 'Dalton minus Rio Mora is not a direct Cowles measurement.']}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--start',default='2026-11-01',help='Inclusive local date YYYY-MM-DD')
    ap.add_argument('--end',default='2026-11-10',help='Inclusive local date YYYY-MM-DD')
    ap.add_argument('--out',default='pecos_instantaneous_history')
    a=ap.parse_args(); start=date.fromisoformat(a.start);end=date.fromisoformat(a.end)
    if start>end:ap.error('--start must not be later than --end')
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    rows=collect(start,end)
    with (out/'instantaneous_flows.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader();writer.writerows(rows)
    summary=audit(rows,start,end)
    (out/'instantaneous_manifest.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))
    if not rows:raise SystemExit('No observations returned; inspect API response and site coverage.')

if __name__=='__main__':main()
