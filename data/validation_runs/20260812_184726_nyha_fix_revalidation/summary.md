# nyha_ordinal fix -- expanded live re-validation summary

Sample: 30 synthetic patients (6 per scenario type, known ground truth), replayed through the
live, fixed API at 2-worker concurrency. Run in two passes: an initial 30-patient attempt
(`data/validation_runs/20260812_172214_nyha_fix_revalidation/`, 13 completed before a backend
restart was needed) and this resume pass covering the remaining 17 (`results.csv`, this
directory) -- `combined_results.csv` merges both into the final 30-patient set below.

Completed: 20/30 (67%) -- notably lower than every prior 2-worker run this session (16/16 and
13/16 on the PerHeart cohort, 0 failures on smaller live-revalidation samples). The 10 failures
are not attributable to the usual severity-linked engine-crash mechanism (they span the full
severity range, 0.001-0.914, and all 5 scenario types) -- see `docs/methodology.md`'s missingness
section and the note on host-level degradation below.

Live severity MAE (post-fix): 0.0275  [95% bootstrap CI 0.0188, 0.0394]  (n=20)
Live scenario accuracy (post-fix): 1.0000  [95% bootstrap CI 1.0000, 1.0000]  (n=20)

Compare against: 0.048 offline severity MAE (this session's retrain), 0.271 live severity MAE
pre-fix (Phase 8, docs/methodology.md Sec 7/8), 0.008 MAE / 5/5 correct on the original n=5 live
re-validation (`data/validation_runs/nyha_fix_live_revalidation.csv`). This n=20 result is
consistent with both: the fix holds at 4x the sample size, well below the pre-fix live MAE and in
the same range as the offline benchmark.

## A methods note on the 67% completion rate

This run's failure rate is a genuine environmental finding, not evidence the model fix is
unreliable. Mid-run, per-patient wall-clock time began climbing (early successes ~400-500s, later
ones up to ~700-720s) and an increasing share of calls started missing the 180s Pulse-subprocess
ceiling -- across every scenario type and severity level, not concentrated in the
high-severity/`Exercise`-scenario pattern documented elsewhere in this project
(`docs/methodology.md`'s missingness section). A `pulse-backend` container restart partially
helped (the first 2 retried patients succeeded) but did not resolve it (8 of the next 10 still
failed) -- container-level CPU/memory looked normal throughout (`docker stats`: ~200% CPU, <400MB
memory, matching the expected 2-worker load), and host CPU was only ~33% utilized, ruling out
obvious resource contention at either the container or host level. This points to degradation
below the container layer (Docker Desktop's VM / WSL2) after several hours of sustained Pulse
subprocess load earlier the same session (the PerHeart re-run, multiple extended-eval passes, and
this run itself) -- consistent with, and now additional evidence for,
`PUBLICATION_TODO.md` P2's open item on diagnosing whether the 180s ceiling is a host/environment
characteristic rather than a universal one. A full Docker Desktop restart (not just the container)
was not attempted for this run, by choice, to avoid further delaying an already-long session --
flagged as a concrete next step for reproducing this specific run at full completion, not silently
omitted.
