# Ethics & Data-Availability Statement (draft)

**Status: first draft, for review before submission.** This assembles what this project can
already answer from its own documented data provenance and validation work; the items marked
"needs your input" below are genuinely Kaveri's call (institutional/journal-specific), not
guessed here.

## Data sources and their ethics/consent basis

| Source | Role in this project | Ethics/consent basis |
|---|---|---|
| MIMIC-IV (`mimic_bigquery_extract`) | Reference statistics (age, sex, height/weight, labs) for the synthetic patient generator | PhysioNet-credentialed access; MIMIC-IV is a de-identified, IRB-approved research database (Beth Israel Deaconess Medical Center / MIT) — de-identification and the PhysioNet Data Use Agreement are the standard basis cited by all MIMIC-derived research, not something this project separately sought approval for. |
| Kaggle — Chicco & Jurman (2020) HF clinical records | EF, serum creatinine/sodium reference statistics | Publicly released, de-identified secondary dataset (UCI Machine Learning Repository origin); no additional consent process applicable. |
| CDC NHANES | Height/weight/BMI-by-sex reference statistics | US federal public-health survey, de-identified, designed for public secondary research use. |
| **PerHeart Pilot Dataset** (real-world validation, `docs/real_world_data_integration.md`) | 27 real HF patients' home pulse-oximeter/scale/BP-cuff readings, replayed through the live pipeline | **Ethics-approved**: Jagiellonian University Ethics Committee, ref. `1072.6120.17.2023` (approved 2023-02-15); written informed consent obtained from all 27 participants by the dataset's original authors (Kolakowski et al., *Data* 2026). This project did not collect the data and had no participant contact — it is a secondary reuse of an already-approved, already-published dataset. |

**License handling note** (already documented in full at `docs/real_world_data_integration.md`
§2.1, referenced here because it's an integrity-relevant fact for a data-availability statement):
Zenodo's structured metadata for the PerHeart record declares CC-BY-4.0, but the dataset's own
bundled `load_dataset.py` states CC-BY-NC-SA in a footer comment. This project treated the more
restrictive reading as binding without contacting the authors to reconcile it — raw PerHeart files
are gitignored and never redistributed; only derived, de-identified model outputs (risk scores,
scenario classifications) are committed, keyed to an internal identifier, not any PerHeart
participant identifier.

## What still needs your input

- **IRB requirement at your own institution.** This project performed no primary human-subjects
  data collection (every real-data source above is a secondary reuse of an already-approved,
  already-published, de-identified dataset) — but whether your institution's IRB still wants a
  determination-of-exemption on file for a paper reusing de-identified third-party data varies by
  institution. Check with your IRB office directly; this is not something to guess from the repo.
- **Target-journal data-availability-statement format.** Journals differ on exactly what's
  required (a data-availability statement naming each source + its access terms is standard; some
  also want a formal statement confirming no primary human-subjects data was collected). Once a
  target journal is chosen, its author guidelines should be checked against the table above.
- **PerHeart license discrepancy — worth resolving before submission**, not just handling
  defensively. The `docs/real_world_data_integration.md` §2.1 approach (assume the more
  restrictive license) is safe for this project's own repo, but a paper citing PerHeart should
  ideally note the discrepancy explicitly, or better, have contacted the dataset authors to
  resolve it — consider doing that before submission rather than only documenting the discrepancy
  internally.

## Real clinical outcome validation — the open item this statement can't paper over

`HANDOFF.md` P1 flags this as the single biggest gap between "systems demo" and "clinical research
paper": every validation performed so far (synthetic data, and PerHeart's real physiological
inputs) shows the pipeline runs correctly on real inputs, not that its risk predictions correlate
with real clinical outcomes. That gap is a substantive limitation to state plainly in the paper's
own limitations section, not something an ethics statement resolves.
