# Related Work / Positioning (draft)

**Status: first-pass literature scan, not a systematic review.** Every source below was found via
web search and its title/venue/URL verified to be real (not recalled from memory — see the MAGGIC
sourcing issue this project ran into elsewhere for why that distinction matters). Full
bibliographic details (complete author lists, exact page numbers, final citation formatting)
should be pulled from each paper directly before submission — what's here is enough to locate and
read each one, not a submission-ready reference list.

## 1. Wearable-based HF deterioration prediction (data-driven, non-mechanistic)

The dominant existing approach: train a model directly on wearable/sensor time series to predict
an HF event, without an underlying physiology model.

- **LINK-HF-style multi-sensor prediction**: "Continuous Wearable Monitoring Analytics Predict
  Heart Failure Hospitalization," *Circulation: Heart Failure* (AHA Journals) —
  https://www.ahajournals.org/doi/10.1161/CIRCHEARTFAILURE.119.006513. A multicenter study (~100
  patients) combining two wearable sensors (HR, respiratory rate, activity, posture) with an ML
  model, reporting 76-87.5% sensitivity / 85% specificity and a median 6.5-day lead time before
  hospitalization.
- **Broader remote-monitoring/wearables survey**: "Artificial Intelligence, Wearables and Remote
  Monitoring for Heart Failure: Current and Future Applications," *Diagnostics* (MDPI) —
  https://www.mdpi.com/2075-4418/12/12/2964.
- **Recent non-invasive decompensation prediction**: "Non-Invasive Wearable Technology to Predict
  Heart Failure Decompensation," *Journal of Clinical Medicine* (MDPI) —
  https://www.mdpi.com/2077-0383/14/20/7423.
- **Seismocardiography/PPG-derived hemodynamics**: SEISMIC-HF 1 — estimates pulmonary capillary
  wedge pressure from a wearable patch (seismocardiography + PPG + ECG) —
  https://pmc.ncbi.nlm.nih.gov/articles/PMC12296972/.

**How this project relates**: this project's own wearable-trend layer
(`src/data_synthesis/generate_wearable_trends.py`, `src/analytics/deterioration_rate.py`) is in
this same tradition (resting HR, SpO2, weight, sleep, steps, HRV trends → deterioration signal),
but it's an *input* to a mechanistic physiology simulation (Pulse) rather than the final
predictive model itself — closer in spirit to the digital-twin literature below than to a
pure end-to-end wearable classifier.

## 2. Heart-failure digital twins (mechanistic/physiology-based)

- **Interpretable HF digital twins for diagnosis/prognosis**: "Identification of digital twins to
  guide interpretable AI for diagnosis and prognosis in heart failure," *npj Digital Medicine*
  (2025) — https://www.nature.com/articles/s41746-025-01501-9. Mechanistic cardiovascular models
  fit to 343 real HF patients, with unsupervised ML on the fitted digital-twin parameters
  identifying interpretable phenogroups tied to cardiovascular-death risk.
- **Right heart failure digital twins**: "Digital twins for noninvasively measuring predictive
  markers of right heart failure," *npj Digital Medicine* (2025) —
  https://www.nature.com/articles/s41746-025-01920-8. 3D CFD-based hemodynamic digital twins,
  validated against invasive measurements.
- **Framing/premise piece**: "Digital Twins and Artificial Intelligence in Heart Failure: The
  Premise and the Promise," *ScienceDirect* —
  https://www.sciencedirect.com/science/article/abs/pii/S1071916426000023.

**How this project relates**: both papers above build a digital twin fit to a *single* real
patient's measured data (individual-level mechanistic personalization). This project instead uses
Pulse as a *shared, population-tunable* physiology engine — a synthetic/wearable-trend-driven
scenario is constructed per patient (`src/patient_builder/`) and run through the same engine,
without per-patient parameter fitting to invasive measurements. That's a real difference worth
stating plainly: this project's "digital twin" claim is weaker in the personalization sense (no
per-patient model fitting) but broader in the deployability sense (no invasive measurement
required to construct one — the entire point of using wearable-derived trends as the twin's
input instead).

## 3. Where this project sits

The combination this project is actually claiming novelty for is the *pipeline*, not any single
component: wearable-trend deterioration signal → ML scenario classification
(`src/scenario_classifier/`) → physiology-engine simulation (Pulse) → a hand-tuned, clinically
cited risk score (`src/analytics/risk_score.py`) with an explicit, documented failure-mode
analysis (`docs/methodology.md`'s missingness/failure-mechanism section) → forward projection.
Most cited work above does one or two of these stages, not the full chain. The honest limitation
to state alongside that claim: **novelty of pipeline design is not the same as validated clinical
accuracy** — see `HANDOFF.md` P1's still-open "real clinical outcome validation" item, and the
`docs/benchmark_comparison.md` MAGGIC comparison (modest positive correlation, r≈0.48, on the
Phase 4 synthetic batch — a sanity check, not proof of clinical validity).

## Not yet covered here (scope for a fuller pass)

A systematic review would also want: HF risk-score literature specifically (Seattle HFM, MAGGIC,
GWTG-HF — already engaged directly via `docs/benchmark_comparison.md` rather than surveyed here),
synthetic-patient-generation methodology literature (this project's own approach in
`src/data_synthesis/` isn't compared against alternatives), and a more exhaustive digital-twin
survey beyond the 3 papers above. Flagged as a gap, not silently omitted.
