# nyha_ordinal fix -- expanded live re-validation summary

Sample: 23 synthetic patients (10 per scenario type, known ground truth), replayed through the live, fixed API at 2-worker concurrency.
Completed: 45/50

Live severity MAE (post-fix): 0.0264  [95% bootstrap CI 0.0194, 0.0352]
Live scenario accuracy (post-fix): 1.0000  [95% bootstrap CI 1.0000, 1.0000]

Compare against: 0.048 offline severity MAE (this session's retrain), 0.271 live severity MAE pre-fix (Phase 8, docs/methodology.md Sec 7/8).
