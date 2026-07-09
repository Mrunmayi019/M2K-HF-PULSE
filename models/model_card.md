# Model Card — M2K HF-PULSE

Covers both trained models in this repo. Written per the roadmap's own convention (planning PDF
§3.4) that a model card is standard ML-engineering practice, not optional polish.

## Model 1 — Scenario Classifier + Severity Regressor (Phase 3)

**Files:** `models/scenario_classifier.joblib`, `models/severity_regressor.joblib` (gitignored,
regenerate with `python3 -m src.scenario_classifier.train`); full report in
`models/phase3_eval_report.txt` (committed).

**Type:** `RandomForestClassifier` (5-class `scenario_type`) + `RandomForestRegressor`
(`severity`, 0–1), `n_estimators=300`, default depth, sharing one feature matrix.

**Training data:** `data/synthetic/patients.csv` + `data/synthetic/wearable_trends.csv`
(synthetic, never real patient data — see `docs/data_provenance.md`), n=2000 patients,
patient-level stratified 70/15/15 split.

**Features:** clinical snapshot (age, sex, BMI, ejection fraction, NT-proBNP, NYHA class) +
21-day wearable-trend aggregates (first/last-7-day mean, delta, slope per vital). See
`docs/methodology.md` §5 for the full feature list and leakage guards.

**Performance (held-out test set, n=300):** 92.3% scenario accuracy (macro F1 0.92), severity MAE
0.048 / RMSE 0.063. Per-class and confusion-matrix detail in `phase3_eval_report.txt`.

**Known limitation:** trained and evaluated entirely on synthetic data whose generative process
makes `scenario_type`/`severity` close to deterministic functions of the input features (see the
discussion in `docs/methodology.md` §5) — high accuracy here reflects a correctly-wired pipeline
more than validated real-world diagnostic performance. No real clinical validation yet.

**Live-pipeline severity performance is materially worse than the table above, with a diagnosed
cause.** A 25-patient batch validation run through the actual API (`scripts/validate_phase8.py`,
full writeup in `docs/methodology.md` §7/§8) measured severity MAE 0.271 in the live pipeline vs.
0.048 offline — `scenario_type` classification was unaffected (100% live agreement). Root cause:
`build_inference_features()` always defaults the `nyha_ordinal` feature to the most-benign class
(`"I"`) at live-inference time, since a genuinely new patient's NYHA class isn't known until this
pipeline itself computes it downstream, whereas offline training used each patient's real, varied
class. This is a train/inference feature-availability mismatch, not a data-generation artifact —
see `docs/methodology.md` §9 for the concrete fix (retrain the severity regressor without
`nyha_ordinal`). Any severity number this system reports live should currently be read as directional,
not precise — the scenario classification and the primary risk score (§6.1, `risk_score.py`) are
not affected by this specific gap.

## Model 2 — Risk Scorer (Phase 5)

Two models exist for the same task (predicting `severity`/risk from one Pulse simulation run's
extracted features: `hr_rise`, `map_drop`, `co_drop_pct`, `compensation_flag`,
`instability_flag`). **They are not peers** — per the locked decision in
`/Users/prakul/Desktop/Pulse-dock/CLAUDE.md` ("Risk scorer"), one is primary and one is
secondary/experimental, and that ordering is load-bearing, not incidental.

### 2a. Primary — hand-tuned weighted score (`src/analytics/risk_score.py`)

**Type:** interpretable weighted linear combination, not a trained/fit model. Each input is
normalized against a clinically-cited anchor (NEWS2 for `hr_rise`, the project's own MAP<65
instability threshold for `map_drop`, a Nohria/SCAI-cited cardiac-output-decline threshold for
`co_drop_pct`) and combined with hand-set weights that sum to 1. Full citations for every anchor
and the weight rationale are in `docs/data_provenance.md` and the module's own docstring.

**Why this is primary:** it requires no training data at all (so the small/imbalanced dataset
below doesn't affect its reliability), and every component of its output is directly explainable
to a clinician — "the score is HIGH because MAP dropped below the shock threshold" is a sentence
a doctor can act on. A black-box prediction is not.

**Validation:** applied to all 117 rows of `data/simulation_runs/features_dataset.csv`; see
`docs/methodology.md` §6 for the severity-correlation check.

### 2b. Secondary/experimental — XGBoost regressor (`src/ml_models/train_risk_scorer.py`)

**File:** `models/risk_scorer_xgb.joblib` (gitignored, regenerate with
`python3 -m src.ml_models.train_risk_scorer`); CV report in `models/phase5_xgb_cv_report.txt`
(committed).

**Type:** `XGBRegressor`, `n_estimators=100`, `max_depth=3`, predicting `severity` from the same 5
features as the primary score.

**Training data:** `data/simulation_runs/features_dataset.csv` — **117 rows**, from a Phase 4
batch of 150 attempted Pulse simulations (33 failed, concentrated in high-severity
`cardiac_stress`/`acute_deterioration` runs; see `docs/methodology.md` §5).

**Evaluation protocol:** 5-fold cross-validation stratified by `scenario_type`, no held-out
train/test split — 117 rows split three ways would leave a ~17-23 row test set, too small for a
trustworthy point estimate. CV gives a defensible generalization estimate instead; the shipped
`.joblib` artifact is refit on the full 117 rows.

**Performance:** MAE 0.089 ± 0.020, R² 0.828 ± 0.091 across folds (see
`phase5_xgb_cv_report.txt` for exact per-fold numbers, regenerate to refresh).

**⚠️ Why this is secondary/experimental only, not primary:**

1. **n=117 is too small for a reliable black-box model.** This is the exact reasoning CLAUDE.md's
   locked decision is built on. A tree ensemble with this little data can fit noise as easily as
   signal, and unlike the primary score, there's no way to independently sanity-check *why* it
   produced a given number — only whether it happened to score well on this run's folds.

2. **The dataset has real, uncorrected class imbalance:** `stable`, `deconditioning`, and
   `fluid_overload` each contribute 30 rows, but `cardiac_stress` only 15 and
   `acute_deterioration` only 12 — because those are the two scenarios whose `Exercise` action
   destabilizes the Pulse engine at higher severities, so a large fraction of their attempted runs
   crashed rather than completing (Phase 4, `docs/methodology.md` §5). **These two
   underrepresented scenarios are also the two most clinically urgent** — `acute_deterioration`
   is by design the most severe scenario in the taxonomy, and `cardiac_stress` is the other
   scenario capable of rapid decompensation under exertion. In other words, the model has seen the
   fewest training examples of exactly the cases where an inaccurate risk score would matter most.
   The 5-fold CV is stratified specifically so every fold sees all 5 classes, but stratification
   only ensures representation *within* each fold — it doesn't fix the underlying scarcity, and
   fold-level R² for the two rare classes should not be assumed to generalize.

**Bottom line:** treat this model's output as a research/comparison signal only. Any
clinician-facing risk number in this system should come from `risk_score.py`, not this model.
