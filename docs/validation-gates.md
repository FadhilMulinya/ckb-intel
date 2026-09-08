# Validation gates

The current repository can verify a frozen exploratory research package. The
following gates remain necessary before stronger scientific or product claims
are made:

| Claim | Required evidence | Current status |
|---|---|---|
| Reproducible frozen package | Released SQLite snapshot, artifact hashes, contracts, and passing offline tests | Implemented; local verification requires the released database digest |
| Representative CKB behaviour | Randomized population sampling with documented inclusion probabilities | Not demonstrated |
| Temporal generality | Multiple non-overlapping observation windows and repeated analysis | Not demonstrated; current result uses one 30-day window |
| Stable behavioural groups | External holdout cohort with predeclared assignment and agreement checks | Not demonstrated |
| Wallet identity classification | Independently verified identity labels and leakage-controlled evaluation | Not available; legacy classifier labels are heuristic proxies |
| Typed-asset analysis | Sufficiently supported, validated raw payload evidence across the cohort | Partial; unsupported or malformed payloads remain missing |
| Production service | Current methodology API, deployment, monitoring, and threat/privacy review | Not part of the final research package |

Passing the offline verifier proves artifact integrity and executable
regression coverage. It does not prove representativeness, causal meaning,
identity attribution, or external predictive performance.