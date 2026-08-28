"""Validation tests for the Phase 4 per-run feature extraction
(src/analytics/simulation_features.py).

Pure-Python, no Docker/Pulse required -- operates on hand-built DataFrames shaped like a real
run_pulse() output.

Run from repo root: pytest tests/test_simulation_features.py -v
"""
import pandas as pd
import pytest

from src.analytics.simulation_features import (
    COMPENSATION_STROKE_VOLUME_RATIO,
    INSTABILITY_MAP_THRESHOLD_MMHG,
    analyze_simulation,
    extract_waveform_data,
    _pick_column,
)


def _make_run(hr, map_, co, sv):
    """Builds a 2-row (start, end) DataFrame with real Pulse-style unit-suffixed column names."""
    return pd.DataFrame(
        {
            "Time(s)": [0, 600],
            "HeartRate(1/min)": hr,
            "MeanArterialPressure(mmHg)": map_,
            "CardiacOutput(mL/min)": co,
            "HeartStrokeVolume(mL)": sv,
            "OxygenSaturation": [0.0, 0.0],  # always flat-0 in real runs -- must be ignored
        }
    )


class TestColumnMatching:
    def test_finds_unit_suffixed_column(self):
        df = _make_run([70, 70], [90, 90], [5000, 5000], [70, 70])
        assert _pick_column(df, "HeartRate") == "HeartRate(1/min)"

    def test_missing_column_raises(self):
        df = _make_run([70, 70], [90, 90], [5000, 5000], [70, 70])
        with pytest.raises(KeyError):
            _pick_column(df, "NotAColumn")


class TestAnalyzeSimulation:
    def test_stable_run_has_no_deltas(self):
        df = _make_run([71, 70], [95, 95], [5000, 5000], [70, 70])
        result = analyze_simulation(df)
        assert result["hr_rise"] == pytest.approx(-1)
        assert result["map_drop"] == 0
        assert result["co_drop_pct"] == 0

    def test_never_uses_oxygen_saturation(self):
        # sanity: even though OxygenSaturation is present (and flat 0.0, as in real runs), no
        # returned key should be derived from it
        df = _make_run([71, 164], [95, 67], [5910, 9948], [60, 82])
        result = analyze_simulation(df)
        assert not any("o2" in k.lower() or "oxygen" in k.lower() for k in result)

    def test_co_drop_pct_sign_when_co_rises(self):
        # cardiac_stress-like healthy compensation: CO rises under exertion -> negative "drop"
        df = _make_run([71, 164], [95, 67], [5910, 9948], [60, 82])
        result = analyze_simulation(df)
        assert result["co_drop_pct"] < 0

    def test_co_drop_pct_sign_when_co_falls(self):
        df = _make_run([72, 132], [78, 52], [6000, 4000], [65, 40])
        result = analyze_simulation(df)
        assert result["co_drop_pct"] > 0

    def test_compensation_flag_true_when_stroke_volume_holds(self):
        # cardiac_stress-like: stroke volume holds/rises despite HR spike
        df = _make_run([71, 164], [95, 67], [5910, 9948], [60, 82])
        result = analyze_simulation(df)
        assert result["compensation_flag"] == 1

    def test_compensation_flag_false_when_stroke_volume_collapses(self):
        # acute_deterioration-like: stroke volume can't keep up despite HR rise
        df = _make_run([72, 132], [78, 52], [4557, 8972], [63, 40])
        result = analyze_simulation(df)
        assert result["compensation_flag"] == 0

    def test_instability_flag_true_below_map_threshold(self):
        df = _make_run([72, 132], [78, 52], [4557, 8972], [63, 40])
        assert INSTABILITY_MAP_THRESHOLD_MMHG > 52  # sanity on the fixture itself
        result = analyze_simulation(df)
        assert result["instability_flag"] == 1

    def test_instability_flag_false_above_map_threshold(self):
        df = _make_run([71, 70], [95, 90], [5000, 5100], [70, 71])
        result = analyze_simulation(df)
        assert result["instability_flag"] == 0

    def test_returns_expected_keys(self):
        df = _make_run([71, 70], [95, 90], [5000, 5100], [70, 71])
        result = analyze_simulation(df)
        assert set(result.keys()) == {
            "hr_start", "hr_end", "hr_rise",
            "map_start", "map_end", "map_drop",
            "co_start", "co_end", "co_drop_pct",
            "stroke_volume_start", "stroke_volume_end",
            "compensation_flag", "instability_flag",
        }


def _make_waveform_run():
    """11 rows, Time(s) 0..10 at a 1s step, constant HR=60 -> cycle_duration_s=1.0 exactly, so
    the tail-window cutoffs land on whole seconds and are easy to hand-verify."""
    return pd.DataFrame(
        {
            "Time(s)": list(range(11)),
            "HeartRate(1/min)": [60] * 11,
            "LeftHeart-Volume(mL)": [i * 10 for i in range(11)],
            "LeftHeart-Pressure(mmHg)": [float(i) for i in range(11)],
            "ECG-Lead3ElectricPotential(mV)": [round(i * 0.01, 3) for i in range(11)],
        }
    )


class TestExtractWaveformData:
    def test_cycle_duration_from_end_heart_rate(self):
        result = extract_waveform_data(_make_waveform_run())
        assert result["cycle_duration_s"] == pytest.approx(1.0)

    def test_pv_loop_is_exactly_one_cycle(self):
        # cutoff = final_time(10) - 1*cycle_s(1.0) = 9 -> rows at Time=9,10
        result = extract_waveform_data(_make_waveform_run())
        assert result["pv_loop"] == [
            {"volume_ml": 90.0, "pressure_mmhg": 9.0},
            {"volume_ml": 100.0, "pressure_mmhg": 10.0},
        ]

    def test_ecg_covers_display_cycles_with_time_relative_to_window_start(self):
        # cutoff = final_time(10) - 3*cycle_s(1.0) = 7 -> rows at Time=7,8,9,10, t_s rebased to 0
        result = extract_waveform_data(_make_waveform_run())
        assert result["ecg"] == [
            {"t_s": 0.0, "mv": 0.07},
            {"t_s": 1.0, "mv": 0.08},
            {"t_s": 2.0, "mv": 0.09},
            {"t_s": 3.0, "mv": 0.1},
        ]

    def test_returns_expected_top_level_keys(self):
        result = extract_waveform_data(_make_waveform_run())
        assert set(result.keys()) == {"cycle_duration_s", "pv_loop", "ecg"}
