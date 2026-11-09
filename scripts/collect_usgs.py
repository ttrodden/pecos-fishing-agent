#!/usr/bin/env python3
"""Pecos Fishing Agent: retrieve and validate official USGS observations."""

import json
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

STATIONS = {"dalton": "08378500", "rio_mora": "08377900"}
PARAMETERS = {"00060": "discharge_cfs", "00065": "gage_height_ft", "00010": "water_temp_c"}
LOCAL = ZoneInfo("America/Denver")
OUTPUT = Path("data/latest.json")
BASE_URL = "https://waterservices.usgs.gov/nwis/iv/"

def fetch():
    query = urllib.parse.urlencode({
        "format": "json",
        "sites": ",".join(STATIONS.values()),
        "parameterCd": ",".join(PARAMETERS),
        "period": "P2D",
        "siteStatus": "all",
    })
    request = urllib.request.Request(
        BASE_URL + "?" + query,
        headers={"User-Agent": "PecosFishingAgent/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)

def parse(payload):
    observations = defaultdict(lambda: defaultdict(dict))
    for series in payload.get("value", {}).get("timeSeries", []):
        site = series.get("sourceInfo", {}).get("siteCode", [{}])[0].get("value")
        code = series.get("variable", {}).get("variableCode", [{}])[0].get("value")
        if site not in STATIONS.values() or code not in PARAMETERS:
            continue
        for block in series.get("values", []):
            for item in block.get("value", []):
                try:
                    timestamp = datetime.fromisoformat(
                        item["dateTime"].replace("Z", "+00:00")
                    ).astimezone(timezone.utc)
                    value = float(item["value"])
                except (KeyError, TypeError, ValueError):
                    continue
                    if value < 0:
                    continue
                stamp = timestamp.isoformat().replace("+00:00", "Z")
                observations[site][code][stamp] = value
    return observations

def main():
    retrieved_at = datetime.now(timezone.utc)
    observations = parse(fetch())

    dalton = observations[STATIONS["dalton"]].get("00060", {})
    mora = observations[STATIONS["rio_mora"]].get("00060", {})
    matched = sorted(set(dalton) & set(mora))

    if not matched:
        raise RuntimeError("No synchronized discharge observations found.")

    latest_time = datetime.fromisoformat(matched[-1].replace("Z", "+00:00"))
    age_minutes = (retrieved_at - latest_time).total_seconds() / 60

    if not (-10 <= age_minutes <= 180):
        raise RuntimeError(
            f"Latest matched observations are stale: {age_minutes:.0f} minutes old."
        )

    samples = [
        {
            "timestamp_utc": stamp,
            "dalton_cfs": dalton[stamp],
            "rio_mora_cfs": mora[stamp],
            "cowles_estimated_cfs": round(dalton[stamp] - mora[stamp], 2),
        }
        for stamp in matched
    ]

    result = {
        "source": "Official USGS instantaneous values",
        "retrieved_at_utc": retrieved_at.isoformat(),
        "latest_matched_at_utc": matched[-1],
        "latest_matched_at_mountain": latest_time.astimezone(LOCAL).isoformat(),
        "matched_age_minutes": round(age_minutes, 1),
        "latest": samples[-1],
        "matched_discharge": samples,
        "station_ids": STATIONS,
        "note": "Cowles flow is estimated as Dalton discharge minus Rio Mora discharge. Ungauged gains and losses are not included.",
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(
        f"SUCCESS: {len(samples)} matched observations; "
        f"latest Cowles estimate {samples[-1]['cowles_estimated_cfs']} CFS"
    )

if __name__ == "__main__":
    main()
