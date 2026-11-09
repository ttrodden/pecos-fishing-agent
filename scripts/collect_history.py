#!/usr/bin/env python3
"""Collect historical Pecos daily flows and weather; reject incomplete precipitation."""
import argparse,csv,json,time,urllib.parse,urllib.request
from pathlib import Path
STATIONS={'dalton':'08378500','rio_mora':'08377900'}
POINTS={'cowles_reference':(35.82,-105.66),'upper_pecos_candidate':(35.88,-105.63),'rio_mora_candidate':(35.80,-105.57),'intervening_candidate':(35.73,-105.66)}
def get(url):
    req=urllib.request.Request(url,headers={'User-Agent':'PecosFishingResearch/0.2'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req,timeout=90) as resp:return json.load(resp)
        except Exception:
            if attempt==2:raise
            time.sleep(2**attempt)
def write_rows(path,rows,fields):
    with path.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--start',default='2022-01-01');ap.add_argument('--end',default='2025-12-31');ap.add_argument('--out',default='research_data');a=ap.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    params={'format':'json','sites':','.join(STATIONS.values()),'startDT':a.start,'endDT':a.end,'parameterCd':'00060','statCd':'00003','siteStatus':'all'}
    usgs=get('https://waterservices.usgs.gov/nwis/dv/?'+urllib.parse.urlencode(params))
    flows={}
    for ts in usgs.get('value',{}).get('timeSeries',[]):
        station=ts.get('sourceInfo',{}).get('siteCode',[{}])[0].get('value')
        name=next((k for k,v in STATIONS.items() if v==station),None)
        if not name:continue
        for series in ts.get('values',[]):
            for record in series.get('value',[]):
                day=record['dateTime'][:10]
                try:val=float(record['value'])
                except (ValueError,TypeError):continue
                if val>=0:flows.setdefault(day,{})[name]=val
    rows=[]
    for day,vals in sorted(flows.items()):
        row={'date':day,**vals}
        if all(k in vals for k in STATIONS):row['dalton_minus_mora_cfs']=round(vals['dalton']-vals['rio_mora'],3)
        rows.append(row)
    if not rows:raise RuntimeError('No USGS flow observations returned')
    write_rows(out/'daily_flows.csv',rows,['date','dalton','rio_mora','dalton_minus_mora_cfs'])
    coverage={}
    for name,(lat,lon) in POINTS.items():
        # Do not force ERA5-Land: the previous request returned null for every precipitation field.
        # Let the historical API choose its available source for the requested variables.
        params={'latitude':lat,'longitude':lon,'start_date':a.start,'end_date':a.end,'daily':'precipitation_sum,rain_sum,snowfall_sum,temperature_2m_max,temperature_2m_min','timezone':'America/Denver'}
        payload=get('https://archive-api.open-meteo.com/v1/archive?'+urllib.parse.urlencode(params))
        d=payload.get('daily',{});cols=list(d)
        if 'time' not in d:raise RuntimeError(f'{name}: no daily weather dates returned')
        n=len(d['time'])
        if any(not isinstance(d.get(k),list) or len(d[k])!=n for k in cols):raise RuntimeError(f'{name}: inconsistent weather lengths')
        for k in ['precipitation_sum','rain_sum','snowfall_sum','temperature_2m_max','temperature_2m_min']:
            values=d.get(k)
            valid=sum(x is not None for x in values) if isinstance(values,list) else 0
            coverage.setdefault(name,{})[k]={'valid':valid,'total':n}
            if valid < n*0.95:raise RuntimeError(f'{name}: {k} has only {valid}/{n} values; aborting instead of uploading incomplete weather')
        write_rows(out/f'weather_{name}.csv',[dict(zip(cols,values)) for values in zip(*(d[k] for k in cols))],cols)
    metadata={'period':[a.start,a.end],'station_ids':STATIONS,'provisional_weather_points':POINTS,'weather_source':'Open-Meteo Historical Weather API (automatic model selection)','weather_coverage':coverage,'warnings':['Weather points are provisional and not validated against drainage boundaries.','Historical weather is not an archived operational forecast.','Dalton-minus-Rio-Mora is a proxy, not observed Cowles flow.','No runoff model or calibrated prediction interval has been fitted.']}
    (out/'metadata.json').write_text(json.dumps(metadata,indent=2))
    print('Validated',len(rows),'flow dates and',len(POINTS),'complete weather series')
if __name__=='__main__':main()
