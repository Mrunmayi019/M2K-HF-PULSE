"""Validation tests for the Phase 5 secondary/experimental XGBoost risk scorer
(src/ml_models/train_risk_scorer.py).

Runs the CV pipeline end-to-end on the real 117-row dataset -- no Docker needed (trains on the
already-generated CSV, never touches Pulse). Deliberately does NOT assert an accuracy/MAE
threshold: with n=117 and real class imbalance (see models/model_card.md), a hardcoded threshold
would be either flaky or false confidence. These tests check the pipeline is wired correctly, not
that the model is good -- that honest framing is the whole point of this model being secondary.

Run from repo root: pytest tests/test_train_risk_scorer.py -v
"""
import pandas as pd
import pytest

from src.ml_models.train_risk_scorer import (
    FEATURE_COLUMNS,
    FEATURES_DATASET_CSV,
    TARGET_COLUMN,
    cross_validate,
    train_final_model,
)


@pytest.fixture(scope="module")
def df() -> pd.DataFrame:
    return pd.read_csv(FEATURES_DATASET_CSV)


class TestCrossValidate:
    def test_returns_expected_keys(self, df):
        result = cross_validate(df, n_folds=5)
        assert set(result.keys()) == {
            "n_folds", "fold_mae", "fold_r2", "mean_mae", "std_mae", "mean_r2", "std_r2",
        }

    def test_correct_number_of_folds(self, df):
        result = cross_validate(df, n_folds=5)
        assert len(result["fold_mae"]) == 5
        assert len(result["fold_r2"]) == 5

    def test_mae_is_non_negative(self, df):
        result = cross_validate(df, n_folds=5)
        assert result["mean_mae"] >= 0
        assert all(v >= 0 for v in result["fold_mae"])

    def test_deterministic_given_seed(self, df):
        a = cross_validate(df, n_folds=5, seed=1)
        b = cross_validate(df, n_folds=5, seed=1)
        assert a["fold_mae"] == b["fold_mae"]


class TestTrainFinalModel:
    def test_fits_on_full_dataset_without_error(self, df):
        model = train_final_model(df)
        preds = model.predict(df[FEATURE_COLUMNS])
        assert len(preds) == len(df)

    def test_predictions_are_finite(self, df):
        model = train_final_model(df)
        preds = model.predict(df[FEATURE_COLUMNS])
        assert all(pd.notna(preds))


def test_dataset_has_the_documented_class_imbalance(df):
    # Sanity check on the exact numbers models/model_card.md commits to in writing.
    counts = df["scenario_type"].value_counts()
    assert counts["cardiac_stress"] == 15
    assert counts["acute_deterioration"] == 12
    assert counts["stable"] == 30
    assert counts["deconditioning"] == 30
    assert counts["fluid_overload"] == 30
    assert len(df) == 117
