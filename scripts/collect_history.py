#!/usr/bin/env python3
"""Exploratory Pecos watershed data collector. Run: python collect_history.py --start 2022-01-01 --end 2025-12-31
Requires internet. No dashboard files are modified. Weather locations are provisional sampling points, NOT delineated watershed centroids.
"""
import argparse,csv,json,time,urllib.parse,urllib.request
from pathlib import Path

STATIONS={'dalton':'08378500','rio_mora':'08377900'}
# Approximate weather sampling locations. Validate against watershed polygons before modeling.
POINTS={'cowles_reference':(35.82,-105.66),'upper_pecos_candidate':(35.88,-105.63),'rio_mora_candidate':(35.80,-105.57),'intervening_candidate':(35.73,-105.66)}

def get(url):
    req=urllib.request.Request(url,headers={'User-Agent':'PecosFishingResearch/0.1 (historical data study)'})
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
    # Daily mean discharge, parameter 00060, statistic 00003.
    params={'format':'json','sites':','.join(STATIONS.values()),'startDT':a.start,'endDT':a.end,'parameterCd':'00060','statCd':'00003','siteStatus':'all'}
    usgs=get('https://waterservices.usgs.gov/nwis/dv/?'+urllib.parse.urlencode(params))
    flows={}
    for ts in usgs.get('value',{}).get('timeSeries',[]):
        station=ts.get('sourceInfo',{}).get('siteCode',[{}])[0].get('value')
        name=next((k for k,v in STATIONS.items() if v==station),None)
        if not name:continue
        for series in ts.get('values',[]):
            for record in series.get('value',[]):
                date=record['dateTime'][:10]
                try:val=float(record['value'])
                except (ValueError,TypeError):continue
                if val>=0:flows.setdefault(date,{})[name]=val
    flowrows=[]
    for day,vals in sorted(flows.items()):
        row={'date':day,**vals}
        if all(k in vals for k in STATIONS):row['dalton_minus_mora_cfs']=round(vals['dalton']-vals['rio_mora'],3)
        flowrows.append(row)
    write_rows(out/'daily_flows.csv',flowrows,['date','dalton','rio_mora','dalton_minus_mora_cfs'])
    for name,(lat,lon) in POINTS.items():
        p={'latitude':lat,'longitude':lon,'start_date':a.start,'end_date':a.end,'daily':'precipitation_sum,rain_sum,snowfall_sum,temperature_2m_max,temperature_2m_min','timezone':'America/Denver','models':'era5_land'}
        payload=get('https://archive-api.open-meteo.com/v1/archive?'+urllib.parse.urlencode(p))
        d=payload['daily'];cols=list(d.keys());write_rows(out/f'weather_{name}.csv',[dict(zip(cols,vals)) for vals in zip(*(d[k] for k in cols))],cols)
    metadata={'period':[a.start,a.end],'station_ids':STATIONS,'provisional_weather_points':POINTS,'weather_model':'ERA5-Land reanalysis','warnings':['Weather points are provisional and not validated against drainage boundaries.','Historical reanalysis is not an archived operational weather forecast.','Daily Dalton-minus-Rio-Mora is a proxy, not directly observed Cowles flow.','No precipitation-to-flow calibration or prediction interval has been fitted.']}
    (out/'metadata.json').write_text(json.dumps(metadata,indent=2))
    print('Saved',len(flowrows),'USGS dates and',len(POINTS),'weather series in',out)
if __name__=='__main__':main()
