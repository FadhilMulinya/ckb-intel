# Frozen Dataset V1

`ckb-behaviour-dataset-v1` contains the immutable 1,172-wallet population `ckb-wallet-population-local-v1`, observed from 2026-08-01 00:00 UTC through 2026-08-31 00:00 UTC (blocks 20,025,197–20,311,450).

| State | Wallets |
|---|---:|
| `COMPLETE` | 939 |
| `PARTIAL` | 6 |
| `FAILED_RETRY_EXHAUSTED` | 224 |
| `FAILED_INVALID_ADDRESS` | 3 |

<<<<<<< HEAD
The snapshot contains 51,816 observed transactions and 92,515 total inputs. Of 56,407 applicable previous-output inputs, all 56,407 resolved. The remaining 36,108 Cellbase inputs are `NOT_APPLICABLE`, not unresolved.
=======
The snapshot contains 51,816 wallet-transaction participation rows (47,145 distinct transaction hashes) and 92,515 total input rows. Of 56,407 applicable previous-output inputs, all 56,407 have `resolution_status=complete`; the normalized `previous_output_index` column is present but null in the frozen rows and is recovered from cached raw JSON by the V2 loader. The remaining 36,108 Cellbase inputs are `NOT_APPLICABLE`, not unresolved.
>>>>>>> 3ffa0873a230edae6a181e1c5144ffb635dd7af6

- Manifest: `6d8b5cd777e9ea9825466dc7500fdcb1dd639981d74475387c405aa6599583fe`
- Database: `e74b12f269c5b5bbc9acb4d39d11e9259769b01299ec0c310d91fd38d43ff322`

Every frozen wallet remains represented. Failed wallets were neither removed nor replaced, and the closed first pass was not retried. Consequently, analyses based only on supported observations can be selection-biased, especially when failure or support varies with activity. Population-wide prevalence claims are not supported.

## Population provenance and scope

The cohort was assembled from overlapping historical local sources, including `ckb_data/addresses.txt` (890 members), prior `ckb_data/ckb_data_v2/provenance` and feature exports (887 each), and the earlier recent-mainnet-activity discovery checkpoint (630). These memberships overlap and are retained per wallet in the research manifest.

<<<<<<< HEAD
Exactly 425 wallets (36.26%) retain a historical `legacy_proxy_label`: 222 `bot_like` and 203 `human_like`; 747 have no such metadata. These values are provenance from the abandoned threshold baseline, not ground truth. They were excluded from Feature V2, PCA, HDBSCAN, GMM, and behavioural interpretation and remain only for auditability.
=======
Exactly 425 wallets (36.26%) retain a historical `legacy_proxy_label`: 222 `bot_like` and 203 `human_like`; 747 have no such metadata. These values are provenance from the abandoned threshold baseline, not ground truth. They were excluded from Feature V2, PCA, HDBSCAN, GMM, and behavioural interpretation and remain only for auditability. The legacy services are retained as historical software and are not the V2 research execution path.
>>>>>>> 3ffa0873a230edae6a181e1c5144ffb635dd7af6

The frozen population is therefore a reproducible observational cohort derived from historical discovery sources—not a random or statistically representative sample of the global CKB wallet population. Structures found here must not be generalized to all CKB wallets without additional sampling validation.

## Database distribution

The approximately 863 MB database is excluded from normal Git history and is distributed through the [Dataset V1 release](https://github.com/FadhilMulinya/ckb-intel/releases/tag/ckb-behaviour-dataset-v1). Download `ckb-behaviour-dataset-v1.sqlite` and place/rename it to `ckb_data/ckb_data_v2/ckb_explorer.sqlite`; its expected SHA-256 is `e74b12f269c5b5bbc9acb4d39d11e9259769b01299ec0c310d91fd38d43ff322`. The offline verifier rejects a missing or mismatched file.
