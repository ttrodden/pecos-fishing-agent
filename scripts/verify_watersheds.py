#!/usr/bin/env python3
"""Independent research tool; never edits the Pecos dashboard.
Requires: pip install requests shapely folium
Usage: python verify_watersheds.py --out watershed_results
Optional: --upper-pecos-lat LAT --upper-pecos-lon LON (verified outlet above The Y)
"""
import argparse, csv, json, time
from pathlib import Path
import requests
from shapely.geometry import shape, mapping, Point
from shapely.ops import unary_union
import folium

BASE='https://api.water.usgs.gov/nldi'
GAUGES={'dalton':'08378500','rio_mora':'08377900','historic_cowles':'08378000'}
POINTS={'cowles_reference':(35.82,-105.66),'upper_pecos_candidate':(35.88,-105.63),'rio_mora_candidate':(35.80,-105.57),'intervening_candidate':(35.73,-105.66)}

def get_json(url, method='GET', payload=None):
    for attempt in range(3):
        try:
            r=requests.request(method,url,json=payload,timeout=100,headers={'User-Agent':'pecos-watershed-research/1.0'})
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):
            if attempt==2: raise
            time.sleep(2**attempt)

def geometry_from_geojson(obj):
    if obj.get('type')=='FeatureCollection':
        geoms=[shape(f['geometry']) for f in obj['features'] if f.get('geometry')]
        if not geoms: raise ValueError('No geometries in FeatureCollection')
        return unary_union(geoms)
    if obj.get('type')=='Feature': return shape(obj['geometry'])
    if obj.get('type') in ('Polygon','MultiPolygon'): return shape(obj)
    raise ValueError('Unrecognized GeoJSON geometry: '+str(obj.get('type')))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--out',default='watershed_results')
    ap.add_argument('--upper-pecos-lat',type=float)
    ap.add_argument('--upper-pecos-lon',type=float)
    args=ap.parse_args()
    if (args.upper_pecos_lat is None)!=(args.upper_pecos_lon is None): ap.error('Provide both upper Pecos coordinates')
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    basins={};errors={}
    for name,site in GAUGES.items():
        url=f'{BASE}/linked-data/nwissite/USGS-{site}/basin?f=json&splitCatchment=true'
        try:
            obj=get_json(url);basins[name]=geometry_from_geojson(obj)
            (out/f'{name}_basin.geojson').write_text(json.dumps({'type':'Feature','properties':{'name':name,'usgs_site':site},'geometry':mapping(basins[name])}))
            print('Retrieved',name)
        except Exception as e:
            errors[name]=str(e);print('Unavailable',name,str(e))
    if args.upper_pecos_lat is not None:
        url=f'{BASE}/pygeoapi/processes/nldi-splitcatchment/execution?f=json'
        try:
            obj=get_json(url,'POST',{'inputs':{'lat':args.upper_pecos_lat,'lon':args.upper_pecos_lon,'upstream':True}})
            candidate=obj.get('drainageBasin') or obj.get('outputs',{}).get('drainageBasin')
            if not candidate: raise ValueError('Response does not contain drainageBasin; inspect service response')
            basins['upper_pecos']=geometry_from_geojson(candidate)
            (out/'upper_pecos_basin.geojson').write_text(json.dumps({'type':'Feature','properties':{'name':'upper_pecos'},'geometry':mapping(basins['upper_pecos'])}))
        except Exception as e: errors['upper_pecos']=str(e);print('Upper Pecos delineation unavailable:',e)
    # Derived incremental drainage: Dalton upstream basin less Rio Mora and upper Pecos.
    if 'dalton' in basins and 'rio_mora' in basins and 'upper_pecos' in basins:
        basins['intervening_incremental']=basins['dalton'].difference(unary_union([basins['rio_mora'],basins['upper_pecos']]))
        (out/'intervening_incremental.geojson').write_text(json.dumps({'type':'Feature','properties':{'name':'intervening_incremental'},'geometry':mapping(basins['intervening_incremental'])}))
    names=list(basins)
    with (out/'weather_point_membership.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['weather_point','latitude','longitude']+[f'inside_{x}' for x in names])
        for n,(lat,lon) in POINTS.items():
            p=Point(lon,lat);w.writerow([n,lat,lon]+[basins[x].covers(p) for x in names])
    m=folium.Map(location=[35.79,-105.65],zoom_start=11,tiles='OpenStreetMap')
    colors={'dalton':'blue','rio_mora':'green','historic_cowles':'purple','upper_pecos':'orange','intervening_incremental':'red'}
    for n,g in basins.items():
        folium.GeoJson(mapping(g),name=n,style_function=lambda feat,c=colors.get(n,'gray'):{'color':c,'weight':2,'fillOpacity':0.13},tooltip=n).add_to(m)
    for n,(lat,lon) in POINTS.items():folium.Marker([lat,lon],tooltip=n,popup=f'{n}: {lat}, {lon}',icon=folium.Icon(color='cadetblue',icon='cloud')).add_to(m)
    if args.upper_pecos_lat is not None:folium.Marker([args.upper_pecos_lat,args.upper_pecos_lon],tooltip='Proposed upper Pecos outlet',icon=folium.Icon(color='orange')).add_to(m)
    folium.LayerControl().add_to(m);m.save(str(out/'watershed_map.html'))
    (out/'verification_status.json').write_text(json.dumps({'basins_retrieved':names,'errors':errors,'upper_pecos_outlet_supplied':args.upper_pecos_lat is not None,'note':'Do not treat provisional weather points as area-weighted watershed climate.'},indent=2))
    print('Results:',out.resolve())
    if errors:print('Some boundaries unavailable; see verification_status.json')
if __name__=='__main__':main()
