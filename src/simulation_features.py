"""Feature extraction from a single Pulse simulation run (Phase 4).

Turns one `run_pulse()` output DataFrame into a fixed set of summary features + flags, used to
build the batch simulation dataset (`src/pulse_runner/batch_runner.py`) that Phase 5's risk scorer
trains on.

Note on placement: this logically belongs in a `src/analytics/` package alongside Phase 5's
`staging.py`/`deterioration_rate.py`/`projection.py` (see docs/architecture.md's target diagram),
but a package directory literally named `analytics` cannot coexist with the existing
`src/analytics.py` prototype module -- `app.py`/`streamlit_app.py` both do
`from src.analytics import analyze` and would break. That collision is explicitly flagged in
architecture.md as unresolved, deferred to whichever phase builds the rest of the package (Phase
5). Kept as a flat module here for now; move into `src/analytics/simulation_features.py` once that
collision is resolved.

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
