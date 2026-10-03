# Zigong-native risk model -- EXPLORATORY, standalone (not part of HeartGuard AI's pipeline)

n raw=2008, n cleaned=2001. Composite outcome (death OR readmission, 6mo) event rate: 41.3%.

## Feature selection

Kept 65/67 candidate fields (<15.0% missing, non-constant). Dropped: ['leukemia', 'LVEF'].
LVEF excluded (68.38% missing, above threshold). brain.natriuretic.peptide (BNP) INCLUDED -- checked at 1.74% missing, well under the bar, correcting an initial assumption it would be dropped like LVEF.
315/2001 rows needed median imputation on at least one already low-missingness field (light imputation only, not applied to any excluded high-missingness field).

## Split & model selection

Stratified 80/20 train/test split on composite_6mo, random_state=42, BEFORE any model selection. 5-fold CV on the training portion only for hyperparameter selection (RandomForestClassifier; grid: {'n_estimators': [300], 'max_depth': [4, 8, None], 'min_samples_leaf': [1, 5, 20]}). Best: {'max_depth': None, 'min_samples_leaf': 5, 'n_estimators': 300} (CV AUC=0.621). Test set touched exactly once, after selection.

## Results

- Train (in-sample): AUC=1.000, PR-AUC=1.000
- **Held-out test (n=401): AUC=0.667 (95% CI 0.611-0.721), PR-AUC=0.605 (95% CI 0.529-0.676), baseline=0.414**
- Train/test AUC gap: 0.333

## Top 15 feature importances

```
urea                                                       0.031343
uric.acid                                                  0.031158
glomerular.filtration.rate                                 0.031017
D.dimer                                                    0.027926
creatinine.enzymatic.method                                0.027369
brain.natriuretic.peptide                                  0.027044
standard.deviation.of.red.blood.cell.distribution.width    0.027029
activated.partial.thromboplastin.time                      0.026577
lymphocyte.count                                           0.025631
prothrombin.activity                                       0.025536
neutrophil.ratio                                           0.025426
hematocrit                                                 0.025425
cystatin                                                   0.023822
red.blood.cell                                             0.023450
white.blood.cell                                           0.023347
```