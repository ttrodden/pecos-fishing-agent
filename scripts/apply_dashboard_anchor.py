#!/usr/bin/env python3
"""Apply fail-closed forecast anchoring improvements to the Pecos dashboard HTML."""
import argparse
from pathlib import Path

VALIDATOR = '''function validatedFlowSeries(j){
 if(!Array.isArray(j.matched_discharge)||!j.matched_discharge.length)throw Error('No synchronized observations');
 const rows=j.matched_discharge.map(v=>({t:Date.parse(v.timestamp_utc),y:Number(v.cowles_estimated_cfs),dalton:Number(v.dalton_cfs),mora:Number(v.rio_mora_cfs)}))
  .filter(v=>Number.isFinite(v.t)&&Number.isFinite(v.y)&&Number.isFinite(v.dalton)&&Number.isFinite(v.mora)&&v.y>=0&&v.dalton>=0&&v.mora>=0&&Math.abs(v.dalton-v.mora-v.y)<0.02)
  .sort((a,b)=>a.t-b.t);
 if(!rows.length)throw Error('No valid matched discharge measurements');
 const unique=[];for(const r of rows){if(unique.length&&unique.at(-1).t===r.t)unique[unique.length-1]=r;else unique.push(r);}
 const end=unique.at(-1),latest=j.latest;
 if(!latest||Date.parse(latest.timestamp_utc)!==end.t||Math.abs(Number(latest.cowles_estimated_cfs)-end.y)>0.02||Math.abs(Number(latest.dalton_cfs)-end.dalton)>0.02||Math.abs(Number(latest.rio_mora_cfs)-end.mora)>0.02)
  throw Error('Latest summary does not match most recent synchronized observation');
 return unique;
}
function assertForecastAnchor(rows,forecast){
 const observed=rows.at(-1),first=forecast[0];
 if(!first||first.t!==observed.t||![first.y,first.lo,first.hi].every(v=>Number.isFinite(v)&&Math.abs(v-observed.y)<1e-8))
  throw Error('Forecast must start at latest valid measured flow with zero-width band');
 if(forecast.some((v,i)=>!Number.isFinite(v.t)||!Number.isFinite(v.y)||!Number.isFinite(v.lo)||!Number.isFinite(v.hi)||v.lo>v.y||v.y>v.hi||(i&&v.t<=forecast[i-1].t)))
  throw Error('Forecast bounds or timestamps are invalid');
}
'''

def patch(s):
    if 'function validatedFlowSeries(j)' in s: raise ValueError('Patch already applied')
    anchor="function model(rows){"
    if s.count(anchor)!=1:raise ValueError('Unexpected model structure')
    s=s.replace(anchor,VALIDATOR+anchor,1)
    old="history=j.matched_discharge.map(v=>({t:Date.parse(v.timestamp_utc),y:Number(v.cowles_estimated_cfs)})).filter(v=>Number.isFinite(v.t)&&Number.isFinite(v.y)).sort((a,b)=>a.t-b.t);if(!history.length)throw Error('Invalid observations');last=history.at(-1);const prediction=model(history);future=prediction.out;"
    new="const validated=validatedFlowSeries(j);const observed=validated.at(-1);const prediction=model(validated);assertForecastAnchor(validated,prediction.out);history=validated;last=observed;future=prediction.out;"
    if s.count(old)!=1:raise ValueError('Unexpected load structure: refusing unsafe patch')
    s=s.replace(old,new,1)
    old="status.textContent=age>180?'Stale observations':`Observed ${stamp(last.t)}`;"
    new="status.textContent=age>180||age< -10?'Stale observations — forecast not current':`Observed ${stamp(last.t)}`;"
    if s.count(old)!=1:raise ValueError('Unexpected status structure')
    s=s.replace(old,new,1)
    old="status.style.background=age>180?'#fff0d7':'#e1f1e9';"
    new="status.style.background=age>180||age< -10?'#fff0d7':'#e1f1e9';"
    s=s.replace(old,new,1)
    old="c.fillText('NOW',x(last.t),p.t-7);canvas._geom={x,y,left,right,w,h,p};"
    new="c.fillText('LAST OBSERVATION',x(last.t),p.t-7);c.beginPath();c.arc(x(last.t),y(last.y),5,0,Math.PI*2);c.fillStyle='#087c90';c.fill();c.strokeStyle='#fff';c.lineWidth=2;c.stroke();c.textAlign=x(last.t)>w-130?'right':'left';c.fillStyle='#152b36';c.fillText(`${fmt(last.y)} CFS`,x(last.t)+(x(last.t)>w-130?-9:9),y(last.y)-10);canvas._geom={x,y,left,right,w,h,p};"
    if s.count(old)!=1:raise ValueError('Unexpected chart marker structure')
    s=s.replace(old,new,1)
    return s

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('input');a.add_argument('output');args=a.parse_args()
    source=Path(args.input).read_text(encoding='utf8')
    Path(args.output).write_text(patch(source),encoding='utf8')
    print('Wrote',args.output)
