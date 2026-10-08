"""BCG/EF ablation, step 3 of 3: measure HR/SV/CO per config and write the tables.

Runs on the HOST (plain pandas), after scripts/bcg_ablation_run.py has produced
data/bcg_ablation/subject*/<config>/full_results.csv and run_status.json.

Measurement: mean of every CSV row (Pulse writes one row per 0.02s engine step) with
Time in [WINDOW_START_S, WINDOW_END_S) -- the final 60s of every 660s run, i.e. 540-600s after the
t=60s action point. Same window for every config. Settling is checked, not assumed: the same means
over the preceding 60s (DRIFT_WINDOW) are compared, and the % change is reported per metric.
"""
from __future__ import annotations

import json
import pathlib

import pandas as pd

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_ROOT = REPO_ROOT / "data" / "bcg_ablation"

WINDOW_START_S, WINDOW_END_S = 600.0, 660.0
DRIFT_WINDOW = (540.0, 600.0)
PRE_ACTION_WINDOW = (0.0, 60.0)  # context only: before any action fires

CHAIN = ["A", "B", "C", "D", "D_HR", "E"]  # "previous config" for the delta column
PREVIOUS = {**{c: CHAIN[i - 1] for i, c in enumerate(CHAIN) if i}, "BCG_only": "A"}
DISPLAY_ORDER = ["A", "BCG_only", "B", "C", "D", "D_HR", "E"]

COLS = {"HR": "HeartRate(1/min)", "SV": "HeartStrokeVolume(mL)", "CO": "CardiacOutput(mL/min)"}


def window_means(df: pd.DataFrame, start: float, end: float) -> dict:
    w = df[(df["Time(s)"] >= start) & (df["Time(s)"] < end)]
    return {k: float(w[c].mean()) for k, c in COLS.items()} | {"n_rows": len(w)}


def main() -> None:
    manifest = json.loads((OUT_ROOT / "manifest.json").read_text())
    status = json.loads((OUT_ROOT / "run_status.json").read_text())
    md = [f"Window: t = {WINDOW_START_S:.0f}-{WINDOW_END_S:.0f} s (mean of all rows). "
          f"Drift = change vs. t = {DRIFT_WINDOW[0]:.0f}-{DRIFT_WINDOW[1]:.0f} s.\n"]

    for subject_id, subj in manifest["subjects"].items():
        real_sv = subj["subject_info"]["sv_ml"]
        real_hr = subj["subject_info"]["hr_bpm"]
        real_co = subj["real_co_ml_min"]
        rows = {}
        for label in DISPLAY_ORDER:
            st = status.get(subject_id, {}).get(label, {"status": "NOT RUN"})
            row = {"config": label, "status": st["status"], "wall_clock_s": st.get("wall_clock_s"),
                   "n_warning_lines": len(st.get("warning_lines", []))}
            csv = OUT_ROOT / f"subject{subject_id}" / label / "full_results.csv"
            if st["status"] == "SUCCESS" and csv.exists():
                df = pd.read_csv(csv)
                m = window_means(df, WINDOW_START_S, WINDOW_END_S)
                d = window_means(df, *DRIFT_WINDOW)
                pre = window_means(df, *PRE_ACTION_WINDOW)
                row.update({
                    "HR": m["HR"], "SV": m["SV"], "CO": m["CO"], "n_rows": m["n_rows"],
                    "HRxSV": m["HR"] * m["SV"],
                    "SV_ratio_real": m["SV"] / real_sv, "CO_ratio_real": m["CO"] / real_co,
                    "HR_ratio_real": m["HR"] / real_hr,
                    **{f"{k}_drift_pct": 100 * (m[k] - d[k]) / d[k] for k in COLS},
                    **{f"{k}_pre_action": pre[k] for k in COLS},
                })
            rows[label] = row

        for label, row in rows.items():
            prev = rows.get(PREVIOUS.get(label, ""), {})
            row["previous"] = PREVIOUS.get(label, "")
            row["dSV_vs_previous"] = row["SV"] - prev["SV"] if "SV" in row and "SV" in prev else None
            row["dCO_vs_previous"] = row["CO"] - prev["CO"] if "CO" in row and "CO" in prev else None

        table = pd.DataFrame(rows.values())
        table.to_csv(OUT_ROOT / f"results_subject{subject_id}.csv", index=False)

        md.append(f"\n### Subject {subject_id} (real SV {real_sv} mL, real HR {real_hr:.0f}, "
                  f"real CO = SV x HR = {real_co:.0f} mL/min)\n")
        md.append("| Config | Status | HR (bpm) | SV (mL) | CO (mL/min) | SV / real | CO / real | "
                  "ΔSV vs previous (mL) | drift HR/SV/CO (%) |")
        md.append("|---|---|---|---|---|---|---|---|---|")
        f = lambda v, p=2: "—" if v is None or pd.isna(v) else f"{v:.{p}f}"
        for r in rows.values():
            delta = "—" if r.get("dSV_vs_previous") is None else f"{r['dSV_vs_previous']:+.2f} (vs {r['previous']})"
            drift = "—" if "SV" not in r else f"{r['HR_drift_pct']:+.2f} / {r['SV_drift_pct']:+.2f} / {r['CO_drift_pct']:+.2f}"
            md.append(f"| {r['config']} | {r['status']} | {f(r.get('HR'))} | {f(r.get('SV'))} | "
                      f"{f(r.get('CO'), 0)} | {f(r.get('SV_ratio_real'), 3)} | {f(r.get('CO_ratio_real'), 3)} | "
                      f"{delta} | {drift} |")

    (OUT_ROOT / "tables.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
