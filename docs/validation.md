# Feature validation

All 121 numeric V2 predictors were checked for missingness, uniqueness, distribution, domain validity, extreme values, scaling, activity association, redundancy, and weekly stability. Results: 17 `USABLE`, 99 `SPARSE`, 5 `CONSTANT`, zero impossible values.

| Available predictor proportion | Wallets |
|---:|---:|
| ≥20% | 493 |
| ≥40% | 300 |
| ≥50% | 300 |
| ≥60% | 257 |
| ≥70% | 249 |
| ≥80% | 230 |
| ≥90% | 179 |

Candidate matrices contain 104 Broad, 95 Core, 59 Low-Redundancy, and 10 High-Confidence predictors. High-Confidence has 513 complete cases. Activity-dependence classifications are 12 HIGH, 22 MODERATE, and 87 LOW. Transaction, Cell, input, and output counts remained diagnostic-only and were excluded from primary discovery matrices. The 59-feature complete-case PCA candidate was rejected at 28 wallets rather than imputed.

Broad and Core are research/diagnostic candidate spaces with substantial sparse-feature participation; they are not equivalent analysis-grade matrices. High-Confidence is the primary complete-case reference used for the strongest PCA and structure conclusions: 10 predictors, 513 wallets, no imputation, selected under documented support and activity criteria. Low-Redundancy remains useful for family-block diagnostics, but its full 59-feature complete-case experiment was rejected because only 28 wallets qualified.
