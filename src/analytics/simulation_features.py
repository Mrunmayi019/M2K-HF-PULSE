"""Feature extraction from a single Pulse simulation run (Phase 4).

Turns one `run_pulse()` output DataFrame into a fixed set of summary features + flags, used to
build the batch simulation dataset (`src/pulse_runner/batch_runner.py`) that Phase 5's risk scorer
trains on.

Never uses `OxygenSaturation` -- it reads a flat 0.0 in every run on this machine (see
docs/methodology.md sections 4 and 8), so it carries no signal.
"""
from __future__ import annotations

import pandas as pd

# Standard critical-care hypoperfusion/shock threshold (e.g. Surviving Sepsis Campaign's MAP >=65
# mmHg resuscitation target) -- see docs/data_provenance.md for the full citation row.
INSTABILITY_MAP_THRESHOLD_MMHG = 65.0

# Tolerance for "stroke volume held up" -- an engineering epsilon (allows small noise-level dips),
# not a clinical claim, so it doesn't need its own data_provenance.md row.
COMPENSATION_STROKE_VOLUME_RATIO = 0.95

_COLUMN_SUBSTRINGS = {
    "heart_rate": "HeartRate",
    "map": "MeanArterialPressure",
    "cardiac_output": "CardiacOutput",
    "stroke_volume": "HeartStrokeVolume",
}

_WAVEFORM_COLUMN_SUBSTRINGS = {
    "left_heart_volume": "LeftHeart-Volume",
    "left_heart_pressure": "LeftHeart-Pressure",
    "ecg": "ECG-Lead3ElectricPotential",
}

# How many cardiac cycles of ECG trace to keep for the dashboard panel -- one cycle alone reads
# as a single ambiguous spike; 3 reads recognizably as a repeating rhythm strip. The PV loop
# panel, in contrast, needs exactly one closed cycle (more would just overplot the same loop).
ECG_DISPLAY_CYCLES = 3


def _pick_column(df: pd.DataFrame, substring: str) -> str:
    """Fuzzy column lookup, matching streamlit_app.py's pick_column() convention -- Pulse's CSV
    columns are unit-suffixed (e.g. "HeartRate(1/min)") so an exact-name match is fragile."""
    lowered = substring.lower()
    for col in df.columns:
        if lowered in col.lower():
            return col
    raise KeyError(f"no column matching {substring!r} found; columns={list(df.columns)}")


def analyze_simulation(df: pd.DataFrame) -> dict:
    """Extracts start/end/delta features and derived flags from one Pulse run's output.

    `df` is the DataFrame returned by src.pulse_runner.runner.run_pulse().
    """
    hr_col = _pick_column(df, _COLUMN_SUBSTRINGS["heart_rate"])
    map_col = _pick_column(df, _COLUMN_SUBSTRINGS["map"])
    co_col = _pick_column(df, _COLUMN_SUBSTRINGS["cardiac_output"])
    sv_col = _pick_column(df, _COLUMN_SUBSTRINGS["stroke_volume"])

    first, last = df.iloc[0], df.iloc[-1]

    hr_start, hr_end = float(first[hr_col]), float(last[hr_col])
    map_start, map_end = float(first[map_col]), float(last[map_col])
    co_start, co_end = float(first[co_col]), float(last[co_col])
    sv_start, sv_end = float(first[sv_col]), float(last[sv_col])

    co_drop_pct = (co_start - co_end) / co_start * 100 if co_start else 0.0
    stroke_volume_ratio = sv_end / sv_start if sv_start else 0.0

    return {
        "hr_start": hr_start,
        "hr_end": hr_end,
        "hr_rise": hr_end - hr_start,
        "map_start": map_start,
        "map_end": map_end,
        "map_drop": map_start - map_end,
        "co_start": co_start,
        "co_end": co_end,
        "co_drop_pct": co_drop_pct,
        "stroke_volume_start": sv_start,
        "stroke_volume_end": sv_end,
        "compensation_flag": int(stroke_volume_ratio >= COMPENSATION_STROKE_VOLUME_RATIO),
        "instability_flag": int(map_end < INSTABILITY_MAP_THRESHOLD_MMHG),
    }


def extract_waveform_data(df: pd.DataFrame) -> dict:
    """Extracts a steady-state ECG trace + pressure-volume (PV) loop window from one Pulse run's
    raw output, for the dashboard's ECG/PV-loop panels (added 2026-08-28; see
    src.patient_builder.scenario_file.DATA_REQUESTS for how these columns were confirmed to exist
    and what they measure).

    Takes the window from the *end* of the run (steady state, matching every "_end" feature in
    analyze_simulation() above) rather than the full run -- the run's raw output is 6000+ rows at
    50Hz, and the early portion is dominated by the 60s stabilization period, not the scenario's
    actual physiological response.
    """
    time_col = next(c for c in df.columns if c.strip().lower().startswith("time"))
    hr_col = _pick_column(df, _COLUMN_SUBSTRINGS["heart_rate"])
    volume_col = _pick_column(df, _WAVEFORM_COLUMN_SUBSTRINGS["left_heart_volume"])
    pressure_col = _pick_column(df, _WAVEFORM_COLUMN_SUBSTRINGS["left_heart_pressure"])
    ecg_col = _pick_column(df, _WAVEFORM_COLUMN_SUBSTRINGS["ecg"])

    final_time = float(df[time_col].iloc[-1])
    hr_end = float(df[hr_col].iloc[-1])
    cycle_s = 60.0 / hr_end if hr_end > 0 else 1.0

    def _tail_window(n_cycles: float) -> pd.DataFrame:
        cutoff = final_time - n_cycles * cycle_s
        return df[df[time_col] >= cutoff]

    pv_window = _tail_window(1)
    ecg_window = _tail_window(ECG_DISPLAY_CYCLES)
    ecg_window_start = float(ecg_window[time_col].iloc[0])

    return {
        "cycle_duration_s": round(cycle_s, 4),
        "pv_loop": [
            {"volume_ml": round(float(v), 2), "pressure_mmhg": round(float(p), 2)}
            for v, p in zip(pv_window[volume_col], pv_window[pressure_col])
        ],
        "ecg": [
            {"t_s": round(float(t) - ecg_window_start, 3), "mv": round(float(v), 4)}
            for t, v in zip(ecg_window[time_col], ecg_window[ecg_col])
        ],
    }
