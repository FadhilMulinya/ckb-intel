# Independent-review delta

| Finding | Resolution | Detail |
|---|---|---|
| Population provenance | `DOCUMENTED` | Verified 1,172 wallets; 425 legacy-labeled (222 `bot_like`, 203 `human_like`), 747 unlabeled; overlapping historical sources disclosed. |
| Sampling/generalization | `DOCUMENTED` | Cohort explicitly described as non-random and not statistically representative globally. |
| CKB `since` limitation | `DOCUMENTED` | Absolute/relative timelock semantics are outside the feature model; enforced vs discretionary lifetime is not distinguished. |
| Broad/Core sparsity | `DOCUMENTED` | Diagnostic sparse spaces separated from the 513×10 no-imputation High-Confidence reference; 28×59 experiment remains rejected. |
| Dependency snapshot | `FIXED` | Flexible requirements retained; exact CPython 3.12.13 artifact-generation versions added in `requirements-research.lock.txt`; independent Python 3.14 verification noted. |
| SQLite `ResourceWarning` | `FIXED` | Store closure is idempotent, context-managed, and exception-safe; regression test passes with ResourceWarning treated as error. |
| 863 MB DB distribution | `FIXED` | Filename, placement, expected SHA, verifier behavior, and the public Dataset V1 release URL are documented. |
| Final-report disclosure | `DOCUMENTED` | Provenance, label exclusion, matrix roles, `since`, generalization, and release instructions added without changing the conclusion. |

## Verification result

- `SCIENTIFIC ARTIFACTS UNCHANGED: YES`
- `DATASET HASH UNCHANGED: YES`
- `POPULATION MANIFEST UNCHANGED: YES`
- `OFFLINE VERIFICATION: PASS`
- `TESTS: 80 PASSING`
- `DOCUMENTATION: READY`
- `PUBLIC DATASET RELEASE: READY`
- `NERVOS SUBMISSION: READY`

Dataset V1 is published at `https://github.com/FadhilMulinya/ckb-intel/releases/tag/ckb-behaviour-dataset-v1`; GitHub reports the expected 862,994,432-byte asset and SHA-256 digest. Remaining human actions: commit/push this reviewed cleanup, optionally verify a full external download, and post the Nervos completion response.
