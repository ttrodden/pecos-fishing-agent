#!/usr/bin/env python3
"""Initial recession-based Cowles River flow prediction model."""

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

INPUT = Path("data/latest.json")
OUTPUT = Path("data/forecast.json")


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main():
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    observations = data["matched_discharge"]

    if len(observations) < 24:
        raise RuntimeError("Insufficient synchronized observations.")

    samples = sorted(
        (
            parse_time(item["timestamp_utc"]),
            float(item["cowles_estimated_cfs"]),
        )
        for item in observations
    )

    latest_time, latest_flow = samples[-1]

    if latest_flow <= 0:
        raise RuntimeError("Latest Cowles flow must be positive.")

    # Use hourly reference values from the preceding 72 hours.
    start = latest_time - timedelta(hours=72)
    recent = [(t, q) for t, q in samples if t >= start and q > 0]

    hourly = {}
    for t, q in recent:
        hour = t.replace(minute=0, second=0, microsecond=0)
        hourly[hour] = q

    points = sorted(hourly.items())

    if len(points) < 24:
        raise RuntimeError("Insufficient recent hourly flow coverage.")

    # Estimate recession using hourly logarithmic changes.
    rates = []
    for (t1, q1), (t2, q2) in zip(points, points[1:]):
        hours = (t2 - t1).total_seconds() / 3600
        if 0 < hours <= 3:
            rates.append(math.log(q2 / q1) / hours)

    if len(rates) < 12:
        raise RuntimeError("Insufficient consecutive flow observations.")

    hourly_rate = median(rates)

    # Detect significant recent rises.
    last_24h = [
        q for t, q in points
        if t >= latest_time - timedelta(hours=24)
    ]

    recent_rise = (
        len(last_24h) >= 12
        and latest_flow > min(last_24h) * 1.15
    )

    recession = hourly_rate < 0 and not recent_rise

    if recession:
        status = "conditional_recession_forecast"
        confidence = "low"
    else:
        status = "unstable_or_rising_flow"
        confidence = "insufficient"

    forecast = []

    for day in range(1, 8):
        target = latest_time + timedelta(days=day)

        if recession:
            predicted = latest_flow * math.exp(
                hourly_rate * 24 * day
            )
            predicted = round(predicted, 1)
        else:
            predicted = None

        forecast.append({
            "day": day,
            "timestamp_utc": target.isoformat(),
            "predicted_cowles_cfs": predicted,
        })

    result = {
        "model": "initial_hourly_median_recession",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "observation_time_utc": latest_time.isoformat(),
        "starting_cowles_cfs": latest_flow,
        "hourly_log_change": round(hourly_rate, 6),
        "status": status,
        "confidence": confidence,
        "forecast": forecast,
        "limitations": [
            "Assumes recession continues without new runoff.",
            "Does not yet include precipitation forecasts.",
            "Does not yet incorporate watershed-specific response.",
            "Does not account for ungauged intervening drainage.",
            "Seven-day predictions are experimental and unvalidated.",
        ],
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        f"SUCCESS: prediction model completed; "
        f"status={status}; "
        f"starting flow={latest_flow:.1f} CFS"
    )


if __name__ == "__main__":
    main()
