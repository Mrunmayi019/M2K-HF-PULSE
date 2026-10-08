"""Compares the ENABLE_SCENARIO_PERSISTENCE=1 scenario-test run (seeds 42-44, written by
run_batch.py with SCENARIO_TEST_OUTPUT_DIR set) against the saved flags-off run, day by day
(feature/wire-research-features, docs/research_flags_evaluation.md Sec 5).

Inputs: results/scenario_tests/daily_results_<p>_seed<s>.csv (flags off) and
results/scenario_tests/flag_runs/scenario_persistence/daily_results_<p>_seed<s>.csv plus its
raw_labels.csv (raw classifier label per day, exported once from dbs/<p>_seed<s>.db,
simulation_runs.raw_scenario_type; the DBs themselves are gitignored).

Twin ALERT/WATCH are the current decide_alert() levels, replayed from each run's saved Pulse
outputs with signal_disagreement_eval.replay() (the same replay research_flags_eval.py uses; the
CSVs' own alert_flag column is the older pre-fix alert, kept here as legacy_alert_flag only).

Sanity check: the classifier never sees Pulse output, so the flag-on run's raw labels must equal
the flags-off run's labels day for day. Writes
results/scenario_tests/posthoc/scenario_persistence_eval.json. No Pulse, runs anywhere:

    PYTHONPATH=. python -m src.evaluation.scenario_tests.scenario_persistence_eval
"""
from __future__ import annotations

import csv
import json
import pathlib
import sqlite3

from src.evaluation.scenario_tests import signal_disagreement_eval as sde

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
OFF_DIR = REPO_ROOT / "results" / "scenario_tests"
ON_DIR = OFF_DIR / "flag_runs" / "scenario_persistence"
OUT_PATH = OFF_DIR / "posthoc" / "scenario_persistence_eval.json"
SEEDS = (42, 43, 44)
GROUPS = ("should_catch", "should_stay_quiet", "edge_case")
PATIENTS = [f"P{i:02d}" for i in range(1, 11)]


def _rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


RAW_LABELS_CSV = ON_DIR / "raw_labels.csv"


def _raw_labels(patient_id, seed):
    """The per-run DBs (dbs/, ~1.4 GB, gitignored) are read once and their raw labels exported to
    raw_labels.csv, which is committed; later runs read the CSV, so the DBs aren't needed."""
    if not RAW_LABELS_CSV.exists():
        with open(RAW_LABELS_CSV, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["patient_id", "seed", "day", "raw_scenario_type"])
            for pid in PATIENTS:
                for s in SEEDS:
                    con = sqlite3.connect(ON_DIR / "dbs" / f"{pid}_seed{s}.db")
                    try:
                        rows = con.execute("SELECT raw_scenario_type FROM simulation_runs ORDER BY id").fetchall()
                    finally:
                        con.close()
                    w.writerows([pid, s, day, label] for day, (label,) in enumerate(rows, start=1))
    return [r["raw_scenario_type"] for r in _rows(RAW_LABELS_CSV)
            if r["patient_id"] == patient_id and int(r["seed"]) == seed]


def _replay(results_dir, patient_id, seed):
    saved = sde.RESULTS_DIR
    sde.RESULTS_DIR = results_dir
    try:
        return sde.replay(patient_id, seed)
    finally:
        sde.RESULTS_DIR = saved


def _summary(days, replayed):
    alert_days = [d["day"] for d in replayed if d["twin"] == "ALERT"]
    return {
        "ALERT": len(alert_days),
        "WATCH": sum(d["twin"] == "WATCH" for d in replayed),
        "ml_ALERT": sum(d["ml"] == "ALERT" for d in replayed),
        "legacy_alert_flag": sum(d["alert_flag"] == "True" for d in days),
        "HIGH_bucket": sum(d["risk_bucket"] == "HIGH" for d in days),
        "MODERATE_bucket": sum(d["risk_bucket"] == "MODERATE" for d in days),
        "failed": sum(d["run_status"] == "failed" for d in days),
        "first_alert_day": min(alert_days) if alert_days else None,
    }


def main():
    out = {"patients": {}, "groups": {g: {"off": {}, "on": {}} for g in GROUPS}, "checks": {}}
    raw_matches_off = True
    for pid in PATIENTS:
        per_seed = {}
        for seed in SEEDS:
            off = _rows(OFF_DIR / f"daily_results_{pid}_seed{seed}.csv")
            on = _rows(ON_DIR / f"daily_results_{pid}_seed{seed}.csv")
            raw = _raw_labels(pid, seed)
            rp_off, rp_on = _replay(OFF_DIR, pid, seed), _replay(ON_DIR, pid, seed)
            # One simulation_runs row per day, failed days included.
            raw_matches_off &= raw == [d["predicted_scenario"] for d in off]
            held = [i + 1 for i, (r, d) in enumerate(zip(raw, on)) if r != d["predicted_scenario"]]
            changed = [
                {"day": int(a["day"]), "label_off": a["predicted_scenario"], "label_on": b["predicted_scenario"],
                 "bucket_off": a["risk_bucket"], "bucket_on": b["risk_bucket"],
                 "alert_off": x["twin"], "alert_on": y["twin"]}
                for a, b, x, y in zip(off, on, rp_off, rp_on)
                if (a["risk_bucket"], x["twin"], a["run_status"]) != (b["risk_bucket"], y["twin"], b["run_status"])
            ]
            per_seed[seed] = {"group": off[0]["expected_group"], "off": _summary(off, rp_off), "on": _summary(on, rp_on),
                              "label_held_days": held, "days_where_outcome_differs": changed}
        group = per_seed[SEEDS[0]]["group"]
        out["patients"][pid] = {
            "group": group,
            "seeds": per_seed,
            "alert_all_seeds_off": all(s["off"]["ALERT"] > 0 for s in per_seed.values()),
            "alert_all_seeds_on": all(s["on"]["ALERT"] > 0 for s in per_seed.values()),
        }
        for side in ("off", "on"):
            tot = out["groups"][group][side]
            for s in per_seed.values():
                for k, v in s[side].items():
                    if k != "first_alert_day":
                        tot[k] = tot.get(k, 0) + v

    out["checks"]["raw_labels_equal_flags_off_labels"] = raw_matches_off
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2))

    print(f"raw labels == flags-off labels: {raw_matches_off}")
    for g, v in out["groups"].items():
        print(f"{g:18s} off={v['off']}  on={v['on']}")
    for pid, p in out["patients"].items():
        s = p["seeds"]
        print(f"{pid} {p['group']:18s} ALERT off/on " + " ".join(f"{s[k]['off']['ALERT']}/{s[k]['on']['ALERT']}" for k in SEEDS)
              + "  first-alert off/on " + " ".join(f"{s[k]['off']['first_alert_day']}/{s[k]['on']['first_alert_day']}" for k in SEEDS)
              + "  held days " + str(sum(len(s[k]['label_held_days']) for k in SEEDS))
              + f"  all-seeds {p['alert_all_seeds_off']}/{p['alert_all_seeds_on']}")


if __name__ == "__main__":
    main()
