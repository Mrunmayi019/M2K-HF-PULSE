# Methodology

Status: skeleton — filled in incrementally as each roadmap phase completes, not written
retroactively before submission. See CLAUDE.md for the decisions already locked (personalization
tiers, scenario taxonomy, dataset strategy, primary risk scorer choice) — this document explains
*why* those decisions were made and how each phase was executed, not what the decisions are.

## 1. Problem Statement

TODO — pull from the presentation script's Slide 2/3 content once finalized (heart failure
readmission problem, monitoring gap between clinic visits).

## 2. Data Sources and Provenance

See `docs/data_provenance.md` for the full parameter-level table. Summary:
- Clinical baselines: synthetic, derived from cited papers + Kaggle datasets (never real patient data)
- Wearable trends: synthetic, 3 modes — `stable`, `deteriorating`, `recovering`
- Simulation dataset: self-generated via Pulse batch runs (Phase 4, not yet started)

## 3. Personalization Tier Design and Justification

See CLAUDE.md "Locked Phase 0 Decisions" — Tier 1 (demographics + EF + BNP + wearables) is core,
Tier 2 (echo PPG) optional/stretch, Tier 3 (ECG-derived BP/contractility) permanently cut.
TODO — write the justification narrative once Tier 2 status is decided.

## 4. Pulse Integration Methodology

TODO — Phase 2, not started. Will document: patient file / scenario file construction, the
EF→contractility and BNP→severity mapping functions (must be isolated, separately testable —
see CLAUDE.md "Working Conventions"), and the crash-detection fix needed in `src/run.py`.

## 5. ML Model Design, Training, Evaluation

TODO — Phase 3 (scenario classifier) and Phase 5 (risk scorer), not started.

## 6. Risk Scoring Logic, With Clinical Citations

TODO — Phase 5. Primary model is the hand-tuned interpretable weighted score (locked decision);
XGBoost on the Pulse batch dataset is secondary/experimental only.

## 7. Validation Approach and Results

TODO. Phase 1 data-synthesis validation lives in `tests/test_data_synthesis.py` for now — this
section will summarize those results once the full dataset is generated.

## 8. Limitations

TODO — write honestly at the end, per CLAUDE.md conventions. Known ones already flagged in the
planning doc: no real clinical validation, wearable sensor error not modeled, small simulation
dataset for the risk scorer, no medication-effect modeling in Pulse scenarios.

## 9. Future Work

TODO. Tier 3 (ECG-derived BP/contractility) belongs here only — never implement it (locked decision).
