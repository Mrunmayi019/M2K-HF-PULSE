"""Calibration pilot, Amendment 1 (c): select the "measurement-consistent" patient set.

Implements the rule in docs/calibration_pilot/pilot_success_criteria.md, Amendment 1 (c),
committed before this script was first run. Filters are applied in the amendment's order, and the
count remaining after each one is logged. Nothing is loosened if fewer than 3 patients pass.

Outputs:
  - data/calibration_pilot/selection_log.md
  - data/calibration_pilot/pilot_patients.csv, rewritten with a `set` column (original /
    consistent) and the extra fields (CO_fick, MRI EDV/ESV/EF, valve grades) for all 6 patients.
    The 3 original rows are rebuilt with calibration_pilot_extract_gu's own helpers, so their
    existing columns keep the same values.

Usage: ./venv/Scripts/python.exe -m scripts.calibration_pilot_select_consistent
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd
import scipy.io as sio

from scripts.calibration_pilot_extract_gu import (
    AGE_ASSUMPTION_YR, GU_MAT_PATH, GU_SEX_CODES, OUT_PATH as PATIENTS_CSV, SOURCE, first_snapshot,
)
from src.patient_builder.patient_file import (
    PULSE_MAX_BMI, PULSE_MIN_BMI, pulse_eligible_age, pulse_eligible_weight_kg,
)

LOG_PATH = PATIENTS_CSV.parent / "selection_log.md"

ORIGINAL_SET = (295, 136, 120)
REQUIRED = ("LVEF_tte", "CO_td", "CO_fick", "HR_vitals", "NIBPs_vitals", "NIBPd_vitals",
            "MRI_LVEDV", "MRI_LVESV", "Height", "Weight", "Sex")
MAX_CO_GAP = 0.10
MAX_EF_GAP_POINTS = 7.0
# Pulse 4.3.1 SetupPatient.cpp: HeartRateBaseline outside [50, 110] bpm is an initialization error.
PULSE_HR_BASELINE_RANGE = (50.0, 110.0)
VALVES = ("AVr", "MVr", "TVr", "PVr")
EF_TARGETS = (25.0, 40.0, 58.0)


def _num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def valve_known_at_most_mild(grade: float, text: str) -> bool:
    """Amendment 1 (c)6: 1.5 = minimal, 2.0 = mild; 1.0 counts only with a "No evidence" text,
    since the same code is also used for "Doppler not available" / "not visualized"."""
    if grade in (1.5, 2.0):
        return True
    return grade == 1.0 and text.strip().lower().startswith("no evidence")


def patient_record(idx: int, s) -> dict:
    """All fields used by the rule and the pilot CSV, for one first snapshot."""
    r = {"gu_index_1based": idx, "gu_patId": int(s.patId)}
    for f in REQUIRED:
        r[f] = _num(getattr(s, f))
    r["PCW"] = _num(s.PCW)
    for v in VALVES:
        r[v] = _num(getattr(s, v))
        r[f"{v}_str"] = str(getattr(s, f"{v}_str"))
    r["bmi"] = r["Weight"] / (r["Height"] / 100.0) ** 2 if r["Height"] > 0 else float("nan")
    r["mri_ef_pct"] = ((r["MRI_LVEDV"] - r["MRI_LVESV"]) / r["MRI_LVEDV"] * 100.0
                       if r["MRI_LVEDV"] > 0 else float("nan"))
    co_mean = (r["CO_td"] + r["CO_fick"]) / 2.0
    r["co_gap_frac"] = abs(r["CO_td"] - r["CO_fick"]) / co_mean if co_mean > 0 else float("nan")
    r["ef_gap_points"] = abs(r["LVEF_tte"] - r["mri_ef_pct"])
    return r


def all_present(r: dict) -> bool:
    for f in REQUIRED:
        x = r[f]
        if not np.isfinite(x):
            return False
        if f == "Sex":
            if x not in GU_SEX_CODES:
                return False
        elif x <= 0:
            return False
    return True


def pilot_row(r: dict, set_name: str) -> dict:
    """Same columns as calibration_pilot_extract_gu's rows, plus the Amendment 1 fields."""
    pulse_weight = pulse_eligible_weight_kg(r["Height"], r["Weight"])
    sbp, dbp = r["NIBPs_vitals"], r["NIBPd_vitals"]
    return {
        "set": set_name,
        "gu_index_1based": r["gu_index_1based"],
        "gu_patId": r["gu_patId"],
        "gu_sex_code": int(r["Sex"]),
        "sex": GU_SEX_CODES[int(r["Sex"])],
        "age": AGE_ASSUMPTION_YR,
        "age_source": "ASSUMED fixed 60 (Birthday is an MCOS datetime, unreadable via scipy)",
        "pulse_age": pulse_eligible_age(AGE_ASSUMPTION_YR),
        "height_cm": r["Height"],
        "weight_kg": r["Weight"],
        "bmi": round(r["bmi"], 2),
        "pulse_weight_kg": round(pulse_weight, 2),
        "weight_clamped_for_pulse": not np.isclose(pulse_weight, r["Weight"]),
        "real_ef_pct": r["LVEF_tte"],
        "real_sbp_mmhg": sbp,
        "real_dbp_mmhg": dbp,
        "real_map_mmhg": round(dbp + (sbp - dbp) / 3, 2),
        "real_co_l_min": r["CO_td"],
        "real_hr_bpm": r["HR_vitals"],
        "real_pcw_mmhg": r["PCW"],
        "real_co_fick_l_min": r["CO_fick"],
        "co_gap_frac": round(r["co_gap_frac"], 4),
        "real_mri_lvedv_ml": r["MRI_LVEDV"],
        "real_mri_lvesv_ml": r["MRI_LVESV"],
        "real_mri_ef_pct": round(r["mri_ef_pct"], 2),
        "ef_gap_points": round(r["ef_gap_points"], 2),
        **{v: r[v] for v in VALVES},
        **{f"{v}_str": r[f"{v}_str"] for v in VALVES},
        "source": SOURCE,
    }


def main() -> None:
    mat = sio.loadmat(GU_MAT_PATH, squeeze_me=True, struct_as_record=False)
    patients = mat["patients"]
    records = [patient_record(i + 1, first_snapshot(p)) for i, p in enumerate(patients)]
    by_idx = {r["gu_index_1based"]: r for r in records}

    steps = [
        ("Required fields all present", all_present),
        (f"CO_td vs CO_fick gap <= {MAX_CO_GAP:.0%} of their mean", lambda r: r["co_gap_frac"] <= MAX_CO_GAP),
        (f"|echo EF - MRI EF| <= {MAX_EF_GAP_POINTS:g} points", lambda r: r["ef_gap_points"] <= MAX_EF_GAP_POINTS),
        (f"{PULSE_MIN_BMI} <= BMI <= {PULSE_MAX_BMI}", lambda r: PULSE_MIN_BMI <= r["bmi"] <= PULSE_MAX_BMI),
        (f"{PULSE_HR_BASELINE_RANGE[0]:g} <= HR_vitals <= {PULSE_HR_BASELINE_RANGE[1]:g} bpm",
         lambda r: PULSE_HR_BASELINE_RANGE[0] <= r["HR_vitals"] <= PULSE_HR_BASELINE_RANGE[1]),
        ("All 4 valves known to be no worse than mild",
         lambda r: all(valve_known_at_most_mild(r[v], r[f"{v}_str"]) for v in VALVES)),
        ("Not one of 295, 136, 120", lambda r: r["gu_index_1based"] not in ORIGINAL_SET),
    ]

    remaining = records
    counts = [("All patients (first snapshot)", len(remaining))]
    before_valve = None
    for name, keep in steps:
        if name.startswith("All 4 valves"):
            before_valve = remaining
        remaining = [r for r in remaining if keep(r)]
        counts.append((name, len(remaining)))

    # Information only (Amendment 1 c6): the looser reading, numeric grade <= 2.0 regardless of text.
    loose = [r for r in before_valve if all(np.isfinite(r[v]) and 1.0 <= r[v] <= 2.0 for v in VALVES)
             and r["gu_index_1based"] not in ORIGINAL_SET]

    passing = sorted(remaining, key=lambda r: r["LVEF_tte"])
    lines = [
        "# Measurement-consistent set — selection log",
        "",
        "Rule: `docs/calibration_pilot/pilot_success_criteria.md`, Amendment 1 (c), committed before "
        "this script was run. Script: `scripts/calibration_pilot_select_consistent.py`. Source: "
        "AllPatients.mat, first snapshot per patient.",
        "",
        "## Patients remaining after each filter",
        "",
        "| Step | Filter | Remaining |",
        "|---|---|---|",
        *[f"| {i} | {name} | {n} |" for i, (name, n) in enumerate(counts)],
        "",
        f"For information only, not used: under the looser valve reading (numeric grade ≤ 2.0 "
        f"regardless of text), {len(loose)} patients would pass instead of {len(remaining)}.",
        "",
    ]

    if len(passing) < 3:
        lines += [f"**STOP: only {len(passing)} patient(s) pass. Nothing picked; rule not loosened.**", ""]
        LOG_PATH.write_text("\n".join(lines), encoding="utf-8")
        print("\n".join(lines))
        sys.exit(1)

    lines += [
        f"## All {len(passing)} passing patients (sorted by echo EF)",
        "",
        "| Index | Sex | Echo EF | MRI EF | EF gap | CO_td | CO_fick | CO gap | HR | BMI | AVr/MVr/TVr/PVr |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
        *[f"| {r['gu_index_1based']} | {GU_SEX_CODES[int(r['Sex'])]} | {r['LVEF_tte']:g} | {r['mri_ef_pct']:.1f} | "
          f"{r['ef_gap_points']:.1f} | {r['CO_td']:g} | {r['CO_fick']:g} | {r['co_gap_frac']:.1%} | "
          f"{r['HR_vitals']:g} | {r['bmi']:.1f} | {'/'.join(f'{r[v]:g}' for v in VALVES)} |" for r in passing],
        "",
        "## Picked",
        "",
    ]

    picked = []
    for target in EF_TARGETS:
        pool = [r for r in passing if r not in picked]
        best = min(pool, key=lambda r: (abs(r["LVEF_tte"] - target), r["co_gap_frac"]))
        ties = [r for r in pool if abs(r["LVEF_tte"] - target) == abs(best["LVEF_tte"] - target)]
        reason = (f"echo EF {best['LVEF_tte']:g} is closest to {target:g} (distance "
                  f"{abs(best['LVEF_tte'] - target):g})")
        if len(ties) > 1:
            reason += (f"; tied with {', '.join(str(t['gu_index_1based']) for t in ties if t is not best)}, "
                       f"won on smaller CO gap ({best['co_gap_frac']:.1%})")
        picked.append(best)
        lines.append(f"- **Target EF {target:g} → patient {best['gu_index_1based']}**: {reason}.")

    LOG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    rows = [pilot_row(by_idx[i], "original") for i in ORIGINAL_SET]
    rows += [pilot_row(r, "consistent") for r in picked]
    pd.DataFrame(rows).to_csv(PATIENTS_CSV, index=False)
    print("\n".join(lines))
    print(f"\nWrote {LOG_PATH} and {PATIENTS_CSV}")


if __name__ == "__main__":
    main()
