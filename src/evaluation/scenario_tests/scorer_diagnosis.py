"""Read-only diagnosis (2026-10-03 follow-up): why does the risk scorer miss P04/P05 and keep P08
HIGH through day 21? Recomputes src.analytics.risk_score.compute_risk_score()'s own component
breakdown from the Pulse start/end features already saved in daily_results_*.csv (pulse_hr_start/
end, pulse_map_start/end, pulse_co_start/end, pulse_compensation_flag, pulse_instability_flag) --
the REAL function, not a reimplementation. No new Pulse runs, no harness/scorer changes.

Usage:
    PYTHONPATH=. python3 -m src.evaluation.scenario_tests.scorer_diagnosis
"""
from __future__ import annotations

import csv
import pathlib

from src.analytics.risk_score import compute_risk_score

RESULTS_DIR = pathlib.Path(__file__).resolve().parents[3] / "results" / "scenario_tests"


def load(pid: str, seed: int):
    with open(RESULTS_DIR / f"daily_results_{pid}_seed{seed}.csv") as f:
        return list(csv.DictReader(f))


def row_components(row: dict) -> dict:
    if row["run_status"] != "complete":
        return None
    hr_start, hr_end = float(row["pulse_hr_start"]), float(row["pulse_hr_end"])
    map_start, map_end = float(row["pulse_map_start"]), float(row["pulse_map_end"])
    co_start, co_end = float(row["pulse_co_start"]), float(row["pulse_co_end"])
    hr_rise = hr_end - hr_start
    map_drop = map_start - map_end
    co_drop_pct = (co_start - co_end) / co_start * 100 if co_start else 0.0
    compensation_flag = int(row["pulse_compensation_flag"])
    instability_flag = int(row["pulse_instability_flag"])
    r = compute_risk_score(
        hr_rise=hr_rise, map_drop=map_drop, co_drop_pct=co_drop_pct,
        compensation_flag=compensation_flag, instability_flag=instability_flag,
        map_start=map_start,
    )
    r["hr_rise"] = round(hr_rise, 2)
    r["map_drop"] = round(map_drop, 2)
    r["map_start"] = round(map_start, 2)
    r["co_drop_pct"] = round(co_drop_pct, 2)
    r["instability_flag"] = instability_flag
    r["compensation_flag"] = compensation_flag
    return r


def dump(pid: str, seed: int):
    rows = load(pid, seed)
    print(f"=== {pid} seed={seed} ===")
    print("day  risk   bucket   instab  map_drop  co_drop%  hr_rise  comp  baseline_deficit  dominant")
    for row in rows:
        c = row_components(row)
        if c is None:
            print(f"{row['day']:>3}  FAILED")
            continue
        comps = c["component_scores"]
        print(
            f"{row['day']:>3}  {c['risk_score']:.4f} {c['risk_bucket']:>8}  "
            f"{comps['instability_flag']:.3f}   {comps['map_drop']:.3f}    {comps['co_drop_pct']:.3f}    "
            f"{comps['hr_rise']:.3f}   {comps['compensation_flag']:.3f}   "
            f"{c['baseline_deficit_score']:.3f}            {c['dominant_mechanism']}"
        )
    print()


if __name__ == "__main__":
    print("--- P05 (all seeds) ---")
    for seed in (42, 43, 44):
        dump("P05", seed)
    print("--- P04 (all seeds) ---")
    for seed in (42, 43, 44):
        dump("P04", seed)
    print("--- P08 (all seeds) ---")
    for seed in (42, 43, 44):
        dump("P08", seed)
