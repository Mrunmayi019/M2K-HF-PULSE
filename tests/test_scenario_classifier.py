"""Validation tests for the Phase 3 scenario classifier / severity regressor.

Run from repo root: pytest tests/test_scenario_classifier.py -v
"""
import pandas as pd
import pytest

from src.data_synthesis.generate_patients import generate_patients
from src.data_synthesis.generate_wearable_trends import generate_wearable_trends
from src.scenario_classifier.features import (
    CLINICAL_FEATURE_COLUMNS,
    TARGET_COLUMNS,
    build_features,
    feature_columns,
)
from src.scenario_classifier.train import SCENARIO_TYPES, run, split_patients

N_PATIENTS = 150
SEED = 7


@pytest.fixture(scope="module")
def patients() -> pd.DataFrame:
    return generate_patients(n=N_PATIENTS, seed=SEED)


@pytest.fixture(scope="module")
def trends(patients: pd.DataFrame) -> pd.DataFrame:
    return generate_wearable_trends(patients, seed=SEED)


@pytest.fixture(scope="module")
def features(patients: pd.DataFrame, trends: pd.DataFrame) -> pd.DataFrame:
    return build_features(patients, trends)


class TestFeatureEngineering:
    def test_one_row_per_patient(self, features, patients):
        assert len(features) == len(patients)
        assert features["patient_id"].is_unique

    def test_expected_columns_present(self, features):
        expected = {"patient_id", *CLINICAL_FEATURE_COLUMNS, *TARGET_COLUMNS}
        assert expected.issubset(features.columns)

    def test_no_missing_values(self, features):
        assert features.isna().sum().sum() == 0

    def test_no_leakage_columns(self, features):
        cols = feature_columns(features)
        assert "trend_mode" not in cols
        assert "scenario_type" not in cols
        assert "severity" not in cols

    def test_wearable_columns_cover_all_vitals(self, features):
        cols = set(feature_columns(features))
        for vital in ["resting_hr_bpm", "spo2_pct", "weight_kg", "steps_per_day", "sleep_hours", "hrv_rmssd_ms"]:
            assert f"{vital}_delta" in cols
            assert f"{vital}_slope" in cols


class TestSplit:
    def test_split_covers_all_patients_no_overlap(self, features):
        train_df, val_df, test_df = split_patients(features, seed=SEED)
        assert len(train_df) + len(val_df) + len(test_df) == len(features)
        ids = [set(train_df["patient_id"]), set(val_df["patient_id"]), set(test_df["patient_id"])]
        assert ids[0].isdisjoint(ids[1])
        assert ids[0].isdisjoint(ids[2])
        assert ids[1].isdisjoint(ids[2])

    def test_split_is_stratified(self, features):
        train_df, val_df, test_df = split_patients(features, seed=SEED)
        for df in (train_df, val_df, test_df):
            assert set(df["scenario_type"].unique()) == set(SCENARIO_TYPES)


@pytest.fixture(scope="module")
def result(patients: pd.DataFrame, trends: pd.DataFrame) -> dict:
    return run(patients, trends, seed=SEED)


class TestTrainEval:
    def test_returns_expected_keys(self, result):
        assert set(result.keys()) == {
            "feature_columns", "classifier", "regressor", "val_metrics", "test_metrics",
        }
        for metrics in (result["val_metrics"], result["test_metrics"]):
            assert set(metrics.keys()) == {
                "accuracy", "classification_report", "confusion_matrix",
                "severity_mae", "severity_rmse", "severity_mae_by_scenario",
            }

    def test_beats_random_guess_baseline(self, result):
        # 5 balanced classes -> random guessing scores ~0.20; a working classifier should clear
        # that by a wide margin even on this small a sample.
        assert result["test_metrics"]["accuracy"] > 0.2

    def test_severity_error_within_sane_bound(self, result):
        # loose sanity bound, not a tuned target -- severity is in [0, 1], so MAE should be a
        # small fraction of the full range for the model to be useful at all.
        assert result["test_metrics"]["severity_mae"] < 1.0

    def test_confusion_matrix_shape(self, result):
        cm = result["test_metrics"]["confusion_matrix"]
        assert cm.shape == (len(SCENARIO_TYPES), len(SCENARIO_TYPES))
