#!/usr/bin/env python3
"""Research-only Pecos basin verification. Does not change dashboard files."""
import argparse, csv, json, time
from pathlib import Path
import requests
from shapely.geometry import shape, mapping, Point
from shapely.ops import unary_union
import folium

BASE = "https://api.water.usgs.gov/nldi"
GAUGES = {"dalton": "08378500", "rio_mora": "08377900", "historic_cowles": "08378000"}
POINTS = {"cowles_reference": (35.82, -105.66),
          "upper_pecos_candidate": (35.88, -105.63),
          "rio_mora_candidate": (35.80, -105.57),
          "intervening_candidate": (35.73, -105.66)}

def request_json(url, method="GET", payload=None):
    last_error = None
    for attempt in range(4):
        try:
            r = requests.request(method, url, json=payload, timeout=75,
                                 headers={"User-Agent": "pecos-watershed-research/1.1",
                                          "Accept": "application/geo+json, application/json"})
            r.raise_for_status()
            if not r.ok:
                print(f"  HTTP {r.status_code} response from {url}: {r.text[:2000]}", flush=True)
            return r.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < 3:
                wait = min(2 ** attempt * 3, 15)
                print(f"  Request failed ({type(exc).__name__}); retrying in {wait}s", flush=True)
                time.sleep(wait)
    raise RuntimeError(f"Request failed after four attempts: {last_error}")

def geometry_from_geojson(obj):
    if obj.get("type") == "FeatureCollection":
        geoms = [shape(f["geometry"]) for f in obj["features"] if f.get("geometry")]
        if not geoms:
            raise ValueError("No geometries in FeatureCollection")
        return unary_union(geoms)
    if obj.get("type") == "Feature":
        return shape(obj["geometry"])
    if obj.get("type") in ("Polygon", "MultiPolygon"):
        return shape(obj)
    raise ValueError(f"Unrecognized GeoJSON geometry: {obj.get('type')}")

def save_basin(out, name, geometry, site=None):
    (out / f"{name}_basin.geojson").write_text(json.dumps({
        "type": "Feature",
        "properties": {"name": name, "usgs_site": site},
        "geometry": mapping(geometry)
    }), encoding="utf-8")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="watershed_results")
    parser.add_argument("--upper-pecos-lat", type=float)
    parser.add_argument("--upper-pecos-lon", type=float)
    parser.add_argument("--rio-mora-outlet-lat", type=float)
    parser.add_argument("--rio-mora-outlet-lon", type=float)
    args = parser.parse_args()
    if (args.upper_pecos_lat is None) != (args.upper_pecos_lon is None):
        parser.error("Provide both upper Pecos coordinates")
    if (args.rio_mora_outlet_lat is None) != (args.rio_mora_outlet_lon is None):
        parser.error("Provide both Rio Mora outlet coordinates")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    basins, errors, methods = {}, {}, {}

    for name, site in GAUGES.items():
        base_url = f"{BASE}/linked-data/nwissite/USGS-{site}/basin"
        # Standard upstream catchments first. More expensive split only if needed later.
        url = base_url + "?f=json&splitCatchment=false"
        print(f"Retrieving {name}: standard basin", flush=True)
        try:
            geom = geometry_from_geojson(request_json(url))
            if geom.is_empty:
                raise ValueError("Empty basin geometry")
            basins[name] = geom
            methods[name] = "NLDI standard basin (whole catchments)"
            save_basin(out, name, geom, site)
            print(f"  Retrieved {name}", flush=True)
        except Exception as exc:
            errors[name] = str(exc)
            print(f"  Unavailable {name}: {exc}", flush=True)

    if args.upper_pecos_lat is not None:
        print("Retrieving point-specific upper Pecos basin", flush=True)
        url = f"{BASE}/pygeoapi/processes/nldi-splitcatchment/execution?f=json"
        try:
            obj = request_json(url, "POST", {"inputs": {
                "lat": args.upper_pecos_lat, "lon": args.upper_pecos_lon, "upstream": True}})
            candidate = obj.get("drainageBasin") or obj.get("outputs", {}).get("drainageBasin")
            if not candidate:
                raise ValueError("No drainageBasin in response; check service schema")
            geom = geometry_from_geojson(candidate)
            if geom.is_empty:
                raise ValueError("Empty upper Pecos geometry")
            basins["upper_pecos"] = geom
            methods["upper_pecos"] = "NLDI point-specific split catchment"
            save_basin(out, "upper_pecos", geom)
        except Exception as exc:
            errors["upper_pecos"] = str(exc)
            print(f"  Upper Pecos unavailable: {exc}", flush=True)
    if args.rio_mora_outlet_lat is not None:
        print("Retrieving point-specific Rio Mora outlet basin", flush=True)
        url = f"{BASE}/pygeoapi/processes/nldi-splitcatchment/execution?f=json"
        try:
            obj = request_json(url, "POST", {"inputs": {
                "lat": args.rio_mora_outlet_lat,
                "lon": args.rio_mora_outlet_lon,
                "upstream": True}})
            candidate = obj.get("drainageBasin") or obj.get("outputs", {}).get("drainageBasin")
            if not candidate:
                raise ValueError("No drainageBasin in Rio Mora response; check service schema")
            geom = geometry_from_geojson(candidate)
            if geom.is_empty:
                raise ValueError("Empty Rio Mora outlet geometry")
            basins["rio_mora_at_y"] = geom
            methods["rio_mora_at_y"] = "NLDI point-specific split catchment"
            save_basin(out, "rio_mora_at_y", geom)
        except Exception as exc:
            errors["rio_mora_at_y"] = str(exc)
            print(f"  Rio Mora outlet unavailable: {exc}", flush=True)
                  
    if all(n in basins for n in ("dalton", "rio_mora_at_y", "upper_pecos")):
        geom = basins["dalton"].difference(
            unary_union([basins["rio_mora_at_y"], basins["upper_pecos"]]))
        if not geom.is_empty:
            basins["intervening_incremental"] = geom
            methods["intervening_incremental"] = "Dalton minus Rio Mora at The Y and upper Pecos at The Y"
            save_basin(out, "intervening_incremental", geom)

    names = list(basins)
    with (out / "weather_point_membership.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["weather_point", "latitude", "longitude"] +
                        [f"inside_{n}" for n in names])
        for name, (lat, lon) in POINTS.items():
            point = Point(lon, lat)
            writer.writerow([name, lat, lon] +
                            [basins[n].covers(point) for n in names])

    map_obj = folium.Map(location=[35.79, -105.65], zoom_start=11)
    colors = {"dalton": "blue", "rio_mora": "green", "historic_cowles": "purple",
              "upper_pecos": "orange", "intervening_incremental": "red"}
    for name, geom in basins.items():
        color = colors.get(name, "gray")
        folium.GeoJson(mapping(geom), name=name,
                       style_function=lambda feature, c=color: {
                           "color": c, "weight": 2, "fillOpacity": 0.13},
                       tooltip=name).add_to(map_obj)
    for name, (lat, lon) in POINTS.items():
        folium.Marker([lat, lon], tooltip=name,
                      popup=f"{name}: {lat}, {lon}",
                      icon=folium.Icon(color="cadetblue", icon="cloud")).add_to(map_obj)
    if args.upper_pecos_lat is not None:
        folium.Marker([args.upper_pecos_lat, args.upper_pecos_lon],
                      tooltip="Proposed upper Pecos outlet").add_to(map_obj)
    folium.LayerControl().add_to(map_obj)
    map_obj.save(str(out / "watershed_map.html"))

    status = {"basins_retrieved": names, "methods": methods, "errors": errors,
              "upper_pecos_outlet_supplied": args.upper_pecos_lat is not None,
              "note": "Gauge basin polygons do not alone establish the Cowles fishing-area drainage."}
    (out / "verification_status.json").write_text(
        json.dumps(status, indent=2), encoding="utf-8")
    print(f"Retrieved {len(basins)} basin geometries. Results: {out.resolve()}", flush=True)
    if not all(name in basins for name in GAUGES):
        raise SystemExit("ERROR: One or more gauge basin boundaries unavailable. See verification_status.json")

if __name__ == "__main__":
    main()
