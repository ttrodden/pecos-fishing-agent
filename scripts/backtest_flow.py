#!/usr/bin/env python3
"""Back-test the Cowles flow recession model using historical observations."""

import csv
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

INPUT = Path("data/latest.json")
OUTPUT = Path("data/backtest_results.csv")

HORIZONS = (1, 2, 3, 7)
LOOKBACK_HOURS = 72
MIN_HISTORY_HOURS = 24


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def estimate_forecast(history):
    """Reproduce the current prediction model using past data only."""
    latest_time, latest_flow = history[-1]

    if latest_flow <= 0:
        return None

    start = latest_time - timedelta(hours=LOOKBACK_HOURS)
    recent = [(t, q) for t, q in history if t >= start and q > 0]

    hourly = {}
    for t, q in recent:
        hour = t.replace(minute=0, second=0, microsecond=0)
        hourly[hour] = q

    points = sorted(hourly.items())

    if len(points) < MIN_HISTORY_HOURS:
        return None

    rates = []
    for (t1, q1), (t2, q2) in zip(points, points[1:]):
        hours = (t2 - t1).total_seconds() / 3600
        if 0 < hours <= 3:
            rates.append(math.log(q2 / q1) / hours)

    if len(rates) < 12:
        return None

    first_flow = median(q for t, q in points[:6])
    last_flow = median(q for t, q in points[-6:])

    elapsed_hours = (
        points[-1][0] - points[0][0]
    ).total_seconds() / 3600

    if elapsed_hours <= 0:
        return None

    hourly_rate = math.log(last_flow / first_flow) / elapsed_hours

    last_24h = [
        q for t, q in points
        if t >= latest_time - timedelta(hours=24)
    ]

    recent_rise = (
        len(last_24h) >= 12
        and latest_flow > min(last_24h) * 1.15
    )

    if hourly_rate >= 0 or recent_rise:
        return {
            "status": "unstable_or_rising_flow",
            "hourly_rate": hourly_rate,
            "predictions": {},
        }

    predictions = {
        day: latest_flow * math.exp(hourly_rate * 24 * day)
        for day in HORIZONS
    }

    return {
        "status": "conditional_recession_forecast",
        "hourly_rate": hourly_rate,
        "predictions": predictions,
    }


def main():
    data = json.loads(INPUT.read_text(encoding="utf-8"))

    samples = sorted(
        (
            parse_time(item["timestamp_utc"]),
            float(item["cowles_estimated_cfs"]),
        )
        for item in data["matched_discharge"]
    )

    if not samples:
        raise RuntimeError("No observations available.")

    # Select historical forecast origins at 24-hour intervals.
    first_origin = samples[0][0] + timedelta(hours=72)
    last_time = samples[-1][0]

    rows = []
    origin = first_origin

    while origin + timedelta(days=1) <= last_time:
        history = [(t, q) for t, q in samples if t <= origin]

        if not history:
            origin += timedelta(days=1)
            continue

        result = estimate_forecast(history)

        if result is None:
            origin += timedelta(days=1)
            continue

        for day in HORIZONS:
            target = origin + timedelta(days=day)

            if target > last_time:
                continue

            actual_candidates = [
                (abs((t - target).total_seconds()), q)
                for t, q in samples
                if abs((t - target).total_seconds()) <= 3600
            ]

            if not actual_candidates:
                continue

            actual = min(actual_candidates)[1]
            predicted = result["predictions"].get(day)

            error = (
                predicted - actual
                if predicted is not None
                else None
            )

            rows.append({
                "origin_utc": origin.isoformat(),
                "horizon_days": day,
                "status": result["status"],
                "hourly_log_change": round(
                    result["hourly_rate"], 6
                ),
                "predicted_cfs": (
                    round(predicted, 1)
                    if predicted is not None
                    else ""
                ),
                "actual_cfs": round(actual, 1),
                "error_cfs": (
                    round(error, 1)
                    if error is not None
                    else ""
                ),
                "absolute_error_pct": (
                    round(abs(error) / actual * 100, 1)
                    if error is not None and actual > 0
                    else ""
                ),
            })

        origin += timedelta(days=1)

    if not rows:
        raise RuntimeError("No valid historical comparisons.")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    fields = [
        "origin_utc",
        "horizon_days",
        "status",
        "hourly_log_change",
        "predicted_cfs",
        "actual_cfs",
        "error_cfs",
        "absolute_error_pct",
    ]

    with OUTPUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    scored = [r for r in rows if r["error_cfs"] != ""]

    print(f"Historical comparisons: {len(rows)}")
    print(f"Numerical forecasts scored: {len(scored)}")

    for day in HORIZONS:
        subset = [
            r for r in scored
            if r["horizon_days"] == day
        ]

        if subset:
            mae = sum(
                abs(r["error_cfs"]) for r in subset
            ) / len(subset)

            print(
                f"Day {day}: {len(subset)} forecasts; "
                f"mean absolute error = {mae:.1f} CFS"
            )
        else:
            print(f"Day {day}: no forecasts available")

    print(f"Results saved to {OUTPUT}")


if __name__ == "__main__":
    main()
