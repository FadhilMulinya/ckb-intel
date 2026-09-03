# Independent-review delta

| Finding | Resolution | Detail |
|---|---|---|
| Population provenance | `DOCUMENTED` | Verified 1,172 wallets; 425 legacy-labeled (222 `bot_like`, 203 `human_like`), 747 unlabeled; overlapping historical sources disclosed. |
| Sampling/generalization | `DOCUMENTED` | Cohort explicitly described as non-random and not statistically representative globally. |
| CKB `since` limitation | `DOCUMENTED` | Absolute/relative timelock semantics are outside the feature model; enforced vs discretionary lifetime is not distinguished. |
| Broad/Core sparsity | `DOCUMENTED` | Diagnostic sparse spaces separated from the 513×10 no-imputation High-Confidence reference; 28×59 experiment remains rejected. |
| Dependency snapshot | `FIXED` | Flexible requirements retained; exact CPython 3.12.13 artifact-generation versions added in `requirements-research.lock.txt`; independent Python 3.14 verification noted. |
| SQLite `ResourceWarning` | `FIXED` | Store closure is idempotent, context-managed, and exception-safe; regression test passes with ResourceWarning treated as error. |
| 863 MB DB distribution | `REQUIRES HUMAN ACTION` | Filename, placement, expected SHA, verifier behavior, and `<DATASET_RELEASE_URL>` placeholder documented. |
| Final-report disclosure | `DOCUMENTED` | Provenance, label exclusion, matrix roles, `since`, generalization, and release instructions added without changing the conclusion. |

## Verification result

- `SCIENTIFIC ARTIFACTS UNCHANGED: YES`
- `DATASET HASH UNCHANGED: YES`
- `POPULATION MANIFEST UNCHANGED: YES`
- `OFFLINE VERIFICATION: PASS`
- `TESTS: 80 PASSING`
- `DOCUMENTATION: READY`
- `PUBLIC DATASET RELEASE: REQUIRES HUMAN ACTION`
- `NERVOS SUBMISSION: READY`

Remaining human actions: commit/push the reviewed repository; publish `ckb-behaviour-dataset-v1.sqlite`; replace `<DATASET_RELEASE_URL>`; independently verify the release download/hash; post the Nervos completion response.
