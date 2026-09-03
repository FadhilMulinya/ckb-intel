# Exploratory ML Phase 1 — PCA and Feature-Space Diagnostics

## A. Frozen-source verification

- Manifest: `6d8b5cd777e9ea9825466dc7500fdcb1dd639981d74475387c405aa6599583fe`
- Database: `e74b12f269c5b5bbc9acb4d39d11e9259769b01299ec0c310d91fd38d43ff322`
- SQLite: `ok`
- Source artifacts unchanged before/after execution.

## B. ML experiment contract

- Experiment: `ckb-exploratory-ml-pca-v1`
- Seed: `20260902`
- Missing-data policy: complete cases only; no imputation.
- PCA: centered covariance eigendecomposition using NumPy.

## C. High-Confidence cohort

Confirmed: **513 wallets × 10 features**.

## D. Transformations

Bounded ratios use StandardScaler. Non-negative magnitudes use log1p then median/IQR scaling. Signed net capacity uses signed-log1p. Zero-IQR columns fall back to mean/std scaling; every decision is recorded.

## E. PCA variance results

- PC1: 0.3924
- PC1+PC2: 0.5803
- First 3: 0.7237
- First 5: 0.8674
- PCs needed: `{'0.5': 2, '0.7': 3, '0.8': 4, '0.9': 6, '0.95': 8}`

## F. Component loadings

Components retain neutral PC names. Strongest signed loadings:

```json
{
  "PC1": {
    "negative": [
      {
        "capacity__target_consumed_capacity": -0.5965667737722913
      },
      {
        "lineage__lineage_depth": -0.546601885813084
      },
      {
        "lineage__continuation_count": -0.4109802099998214
      }
    ],
    "positive": [
      {
        "capacity__target_net_capacity_delta": 0.06903811785029686
      },
      {
        "scripts__type_family_count": -0.006261122710816262
      },
      {
        "scripts__unique_lock_script_count": -0.05699259267002876
      }
    ]
  },
  "PC2": {
    "negative": [
      {
        "lineage__lineage_depth": -0.3999803118231887
      },
      {
        "lineage__continuation_count": -0.39621958653958456
      },
      {
        "lineage__lineage_repetition": -0.27207221528671255
      }
    ],
    "positive": [
      {
        "capacity__target_consumed_capacity": 0.6813762724082781
      },
      {
        "capacity__capacity_repeat_ratio": 0.24060288024241505
      },
      {
        "scripts__type_family_count": 0.030307420021221915
      }
    ]
  },
  "PC3": {
    "negative": [
      {
        "lineage__lineage_repetition": -0.4571697018061404
      },
      {
        "scripts__unique_lock_script_count": -0.3720587393306382
      },
      {
        "lineage__merge_count": -0.3676675868357161
      }
    ],
    "positive": [
      {
        "scripts__type_family_count": 0.5187690688816364
      },
      {
        "lineage__continuation_count": 0.33488160226144115
      },
      {
        "scripts__unique_type_script_count": 0.33109992381954206
      }
    ]
  },
  "PC4": {
    "negative": [
      {
        "lineage__continuation_count": -0.23166200491466607
      },
      {
        "lineage__lineage_depth": -0.17282347798353503
      },
      {
        "capacity__target_net_capacity_delta": -0.026723021330575112
      }
    ],
    "positive": [
      {
        "scripts__type_family_count": 0.7351404024322497
      },
      {
        "lineage__lineage_repetition": 0.32822287949667783
      },
      {
        "lineage__merge_count": 0.30827409886887486
      }
    ]
  },
  "PC5": {
    "negative": [
      {
        "capacity__capacity_repeat_ratio": -0.7106143437820583
      },
      {
        "lineage__lineage_depth": -0.31424537979482076
      },
      {
        "capacity__target_net_capacity_delta": -0.19850688463056088
      }
    ],
    "positive": [
      {
        "lineage__continuation_count": 0.449507863330424
      },
      {
        "capacity__target_consumed_capacity": 0.3057326742719296
      },
      {
        "scripts__unique_lock_script_count": 0.18933170719150957
      }
    ]
  }
}
```

## G. Activity-volume correlations

Maximum PC1–PC5 activity correlation: **0.6997**.
High-association diagnostic relationships: **0**.

```json
{
  "PC1": {
    "absolute_maximum": 0.6996891974138856,
    "association": "MODERATE_ACTIVITY_ASSOCIATION",
    "component": "PC1",
    "diagnostic": "observed_cell_count",
    "pearson": -0.029095242826755272,
    "spearman": -0.6996891974138856
  },
  "PC2": {
    "absolute_maximum": 0.4349338530800005,
    "association": "LOW_ACTIVITY_ASSOCIATION",
    "component": "PC2",
    "diagnostic": "output_count",
    "pearson": -0.023176389413613704,
    "spearman": -0.4349338530800005
  },
  "PC3": {
    "absolute_maximum": 0.6650978116445112,
    "association": "MODERATE_ACTIVITY_ASSOCIATION",
    "component": "PC3",
    "diagnostic": "input_count",
    "pearson": -0.1432909267117102,
    "spearman": -0.6650978116445112
  },
  "PC4": {
    "absolute_maximum": 0.29201028213870656,
    "association": "LOW_ACTIVITY_ASSOCIATION",
    "component": "PC4",
    "diagnostic": "output_count",
    "pearson": 0.04940211824205229,
    "spearman": 0.29201028213870656
  },
  "PC5": {
    "absolute_maximum": 0.05981524373866394,
    "association": "LOW_ACTIVITY_ASSOCIATION",
    "component": "PC5",
    "diagnostic": "input_count",
    "pearson": 0.05981524373866394,
    "spearman": 0.03606619804083701
  }
}
```

## H. Feature-family contribution

```json
{
  "PC1": {
    "contribution": 0.5480051108389098,
    "family": "lineage",
    "single_family_dominance": false
  },
  "PC2": {
    "contribution": 0.5003398859368368,
    "family": "lineage",
    "single_family_dominance": false
  },
  "PC3": {
    "contribution": 0.47528079084767244,
    "family": "lineage",
    "single_family_dominance": false
  },
  "PC4": {
    "contribution": 0.538255008737189,
    "family": "scripts",
    "single_family_dominance": false
  },
  "PC5": {
    "contribution": 0.49135359245564214,
    "family": "capacity",
    "single_family_dominance": false
  }
}
```

Absent temporal/topology/template/lifecycle families are a limitation of High-Confidence support, not evidence that those behaviours are unimportant.

## I. PCA score and extreme-wallet review

PC1–PC5 distributions and five upper/lower extremes are exported with wallet identifiers and evidence-artifact references. No outlier was deleted.

## J. Bootstrap stability

Median PC1–PC5 loading cosine: **0.9839** across 500 deterministic resamples.

## K. Low-Redundancy Core feasibility

```json
[
  {
    "accepted": false,
    "decision": "REJECTED: requires n>=100 and n/p>=5.0; observed n=28, p=59, n/p=0.475",
    "experiment": "PCA_LOW_REDUNDANCY_COMPLETE_CASE_V1",
    "feature_family_composition": {
      "capacity": 8,
      "lifecycle": 5,
      "lineage": 5,
      "scripts": 7,
      "templates": 7,
      "temporal": 13,
      "topology": 14
    },
    "n_features": 59,
    "n_wallets": 28,
    "wallets_per_feature": 0.4745762711864407
  },
  {
    "accepted": true,
    "decision": "ACCEPTED",
    "experiment": "PCA_TEMPORAL_STRUCTURE_BLOCK_V1",
    "feature_family_composition": {
      "templates": 7,
      "temporal": 13,
      "topology": 14
    },
    "n_features": 34,
    "n_wallets": 249,
    "wallets_per_feature": 7.323529411764706
  },
  {
    "accepted": true,
    "decision": "ACCEPTED",
    "experiment": "PCA_CELL_STRUCTURE_BLOCK_V1",
    "feature_family_composition": {
      "capacity": 8,
      "lifecycle": 5,
      "lineage": 5
    },
    "n_features": 18,
    "n_wallets": 172,
    "wallets_per_feature": 9.555555555555555
  },
  {
    "accepted": false,
    "decision": "REJECTED: requires n>=100 and n/p>=5.0; observed n=46, p=36, n/p=1.278",
    "experiment": "PCA_SCRIPT_TRANSACTION_STRUCTURE_BLOCK_V1",
    "feature_family_composition": {
      "capacity": 8,
      "scripts": 7,
      "templates": 7,
      "topology": 14
    },
    "n_features": 36,
    "n_wallets": 46,
    "wallets_per_feature": 1.2777777777777777
  }
]
```

## L. Family-block PCA results

```json
[
  {
    "dominant_families_pc1_pc5": {
      "PC1": {
        "contribution": 0.7805425229545978,
        "family": "templates",
        "single_family_dominance": true
      },
      "PC2": {
        "contribution": 0.6786350535098791,
        "family": "temporal",
        "single_family_dominance": true
      },
      "PC3": {
        "contribution": 0.396334763010299,
        "family": "temporal",
        "single_family_dominance": false
      },
      "PC4": {
        "contribution": 0.5466545234046488,
        "family": "topology",
        "single_family_dominance": false
      },
      "PC5": {
        "contribution": 0.5748868915044658,
        "family": "topology",
        "single_family_dominance": false
      }
    },
    "features": [
      "templates__consecutive_template_repeat_ratio",
      "templates__dominant_template_count",
      "templates__dominant_template_ratio",
      "templates__rare_template_ratio",
      "templates__template_entropy",
      "templates__template_transition_entropy",
      "templates__transition_repeat_ratio",
      "temporal__active_day_concentration",
      "temporal__active_hour_concentration",
      "temporal__burst_count",
      "temporal__gap_entropy",
      "temporal__interarrival_cv",
      "temporal__interarrival_kurtosis",
      "temporal__interarrival_mean_seconds",
      "temporal__interarrival_median_seconds",
      "temporal__interarrival_p10",
      "temporal__interarrival_p75",
      "temporal__interarrival_p90",
      "temporal__interarrival_skewness",
      "temporal__interarrival_std_seconds",
      "topology__consolidation_event_count",
      "topology__dominant_topology_ratio",
      "topology__external_input_lock_mean",
      "topology__fragmentation_event_count",
      "topology__input_cell_count_cv",
      "topology__input_cell_count_mean",
      "topology__input_cell_count_median",
      "topology__many_to_many_ratio",
      "topology__many_to_one_ratio",
      "topology__one_to_many_ratio",
      "topology__one_to_one_ratio",
      "topology__output_cell_count_cv",
      "topology__output_cell_count_mean",
      "topology__topology_entropy"
    ],
    "first_3_variance": 0.8306657864666738,
    "first_5_variance": 0.8878479207816645,
    "high_activity_component_relationships": 0,
    "maximum_pc1_pc5_activity_association": 0.7557369585460462,
    "median_pc1_pc5_loading_stability": 0.9209051000524384,
    "n_features": 34,
    "n_wallets": 249,
    "name": "PCA_TEMPORAL_STRUCTURE_BLOCK_V1",
    "output_directory": "/Users/fadhil/Personal/ckb-intel/ckb_data/exploratory_ml_pca_v1/pca_temporal_structure_block_v1",
    "pc1_pc2_variance": 0.78358753135428,
    "pc1_variance": 0.7283362965219764,
    "status": "EXECUTED",
    "strongest_activity_pc1_pc5": {
      "PC1": {
        "absolute_maximum": 0.5871299647701632,
        "association": "MODERATE_ACTIVITY_ASSOCIATION",
        "component": "PC1",
        "diagnostic": "observed_cell_count",
        "pearson": 0.5871299647701632,
        "spearman": 0.49424165873343767
      },
      "PC2": {
        "absolute_maximum": 0.7557369585460462,
        "association": "MODERATE_ACTIVITY_ASSOCIATION",
        "component": "PC2",
        "diagnostic": "input_count",
        "pearson": 0.34275303883317243,
        "spearman": 0.7557369585460462
      },
      "PC3": {
        "absolute_maximum": 0.3604172092937734,
        "association": "LOW_ACTIVITY_ASSOCIATION",
        "component": "PC3",
        "diagnostic": "output_count",
        "pearson": 0.11626185541809099,
        "spearman": 0.3604172092937734
      },
      "PC4": {
        "absolute_maximum": 0.27922331108014753,
        "association": "LOW_ACTIVITY_ASSOCIATION",
        "component": "PC4",
        "diagnostic": "input_count",
        "pearson": 0.01818912963576936,
        "spearman": 0.27922331108014753
      },
      "PC5": {
        "absolute_maximum": 0.5343864984416065,
        "association": "MODERATE_ACTIVITY_ASSOCIATION",
        "component": "PC5",
        "diagnostic": "output_count",
        "pearson": -0.0969794804109938,
        "spearman": -0.5343864984416065
      }
    },
    "top_loadings_pc1_pc5": {
      "PC1": {
        "negative": [
          {
            "templates__template_transition_entropy": -0.9805490365298544
          },
          {
            "templates__template_entropy": -0.07790589129456948
          },
          {
            "templates__rare_template_ratio": -0.04897857282612169
          }
        ],
        "positive": [
          {
            "templates__consecutive_template_repeat_ratio": 0.10240502963458109
          },
          {
            "templates__dominant_template_ratio": 0.06639988274724337
          },
          {
            "templates__transition_repeat_ratio": 0.06434245422526252
          }
        ]
      },
      "PC2": {
        "negative": [
          {
            "temporal__interarrival_p75": -0.5504367721360763
          },
          {
            "temporal__interarrival_p90": -0.44572148658172756
          },
          {
            "temporal__interarrival_mean_seconds": -0.42304891310061465
          }
        ],
        "positive": [
          {
            "temporal__interarrival_skewness": 0.2582099332726156
          },
          {
            "temporal__interarrival_kurtosis": 0.24510380755990516
          },
          {
            "templates__dominant_template_count": 0.18931059782916804
          }
        ]
      },
      "PC3": {
        "negative": [
          {
            "temporal__interarrival_std_seconds": -0.3689022263072178
          },
          {
            "topology__topology_entropy": -0.32542944201107077
          },
          {
            "temporal__interarrival_cv": -0.32316458965369876
          }
        ],
        "positive": [
          {
            "topology__dominant_topology_ratio": 0.3101604821728382
          },
          {
            "templates__rare_template_ratio": 0.2520364627871345
          },
          {
            "temporal__interarrival_p10": 0.18723929286826133
          }
        ]
      },
      "PC4": {
        "negative": [
          {
            "topology__dominant_topology_ratio": -0.2658701914325599
          },
          {
            "templates__transition_repeat_ratio": -0.26363405392284694
          },
          {
            "templates__dominant_template_ratio": -0.2192940431090307
          }
        ],
        "positive": [
          {
            "topology__many_to_one_ratio": 0.45614125877991635
          },
          {
            "topology__external_input_lock_mean": 0.311503100060625
          },
          {
            "templates__rare_template_ratio": 0.3099576468776845
          }
        ]
      },
      "PC5": {
        "negative": [
          {
            "topology__one_to_many_ratio": -0.29273396836129517
          },
          {
            "topology__topology_entropy": -0.23167143928421538
          },
          {
            "temporal__interarrival_p75": -0.16772942889775772
          }
        ],
        "positive": [
          {
            "topology__many_to_many_ratio": 0.4824130793010818
          },
          {
            "temporal__active_day_concentration": 0.4115585458476885
          },
          {
            "topology__dominant_topology_ratio": 0.2665014529682268
          }
        ]
      }
    },
    "variance_thresholds": {
      "0.5": 1,
      "0.7": 1,
      "0.8": 3,
      "0.9": 6,
      "0.95": 10
    },
    "wallets_per_feature": 7.323529411764706
  },
  {
    "dominant_families_pc1_pc5": {
      "PC1": {
        "contribution": 0.39180482518622295,
        "family": "lifecycle",
        "single_family_dominance": false
      },
      "PC2": {
        "contribution": 0.48803685334576113,
        "family": "capacity",
        "single_family_dominance": false
      },
      "PC3": {
        "contribution": 0.43860841964920877,
        "family": "capacity",
        "single_family_dominance": false
      },
      "PC4": {
        "contribution": 0.36387295541339987,
        "family": "lifecycle",
        "single_family_dominance": false
      },
      "PC5": {
        "contribution": 0.4868494092280198,
        "family": "capacity",
        "single_family_dominance": false
      }
    },
    "features": [
      "capacity__capacity_input_entropy",
      "capacity__capacity_output_entropy",
      "capacity__capacity_repeat_ratio",
      "capacity__input_capacity_cv",
      "capacity__output_capacity_cv",
      "capacity__output_capacity_mean",
      "capacity__target_consumed_capacity",
      "capacity__target_net_capacity_delta",
      "lifecycle__consumed_cell_count",
      "lifecycle__long_lived_cell_ratio",
      "lifecycle__rapid_consumption_ratio",
      "lifecycle__same_block_consumption_ratio",
      "lifecycle__short_lived_cell_ratio",
      "lineage__branch_count",
      "lineage__continuation_count",
      "lineage__lineage_depth",
      "lineage__lineage_repetition",
      "lineage__merge_count"
    ],
    "first_3_variance": 0.5028945777134544,
    "first_5_variance": 0.6929306228877827,
    "high_activity_component_relationships": 0,
    "maximum_pc1_pc5_activity_association": 0.7698296263090812,
    "median_pc1_pc5_loading_stability": 0.7648602099570341,
    "n_features": 18,
    "n_wallets": 172,
    "name": "PCA_CELL_STRUCTURE_BLOCK_V1",
    "output_directory": "/Users/fadhil/Personal/ckb-intel/ckb_data/exploratory_ml_pca_v1/pca_cell_structure_block_v1",
    "pc1_pc2_variance": 0.3664458367557742,
    "pc1_variance": 0.20664953632369476,
    "status": "EXECUTED",
    "strongest_activity_pc1_pc5": {
      "PC1": {
        "absolute_maximum": 0.266188399333007,
        "association": "LOW_ACTIVITY_ASSOCIATION",
        "component": "PC1",
        "diagnostic": "transaction_count",
        "pearson": -0.007620220898089529,
        "spearman": -0.266188399333007
      },
      "PC2": {
        "absolute_maximum": 0.7698296263090812,
        "association": "MODERATE_ACTIVITY_ASSOCIATION",
        "component": "PC2",
        "diagnostic": "output_count",
        "pearson": -0.10867518712598286,
        "spearman": -0.7698296263090812
      },
      "PC3": {
        "absolute_maximum": 0.615131784598645,
        "association": "MODERATE_ACTIVITY_ASSOCIATION",
        "component": "PC3",
        "diagnostic": "output_count",
        "pearson": 0.2352585134772415,
        "spearman": 0.615131784598645
      },
      "PC4": {
        "absolute_maximum": 0.5929794473371837,
        "association": "MODERATE_ACTIVITY_ASSOCIATION",
        "component": "PC4",
        "diagnostic": "observed_cell_count",
        "pearson": -0.019810568965487507,
        "spearman": -0.5929794473371837
      },
      "PC5": {
        "absolute_maximum": 0.2735102261833887,
        "association": "LOW_ACTIVITY_ASSOCIATION",
        "component": "PC5",
        "diagnostic": "observed_cell_count",
        "pearson": -0.021415074115555204,
        "spearman": -0.2735102261833887
      }
    },
    "top_loadings_pc1_pc5": {
      "PC1": {
        "negative": [
          {
            "lifecycle__short_lived_cell_ratio": -0.5052962052672121
          },
          {
            "capacity__capacity_output_entropy": -0.3150242711019395
          },
          {
            "capacity__capacity_input_entropy": -0.31378566090309884
          }
        ],
        "positive": [
          {
            "lifecycle__long_lived_cell_ratio": 0.5029364786985352
          },
          {
            "lineage__continuation_count": 0.289397360615857
          },
          {
            "lineage__lineage_depth": 0.2803056827094119
          }
        ]
      },
      "PC2": {
        "negative": [
          {
            "lineage__lineage_repetition": -0.42384845707582763
          },
          {
            "lifecycle__consumed_cell_count": -0.33185163574534954
          },
          {
            "lineage__merge_count": -0.2713923234023244
          }
        ],
        "positive": [
          {
            "capacity__capacity_output_entropy": 0.4092336160784123
          },
          {
            "capacity__capacity_input_entropy": 0.39479886271099124
          },
          {
            "capacity__output_capacity_mean": 0.24263869834842153
          }
        ]
      },
      "PC3": {
        "negative": [
          {
            "capacity__capacity_repeat_ratio": -0.4734650182478763
          },
          {
            "lifecycle__rapid_consumption_ratio": -0.3438577849583477
          },
          {
            "lifecycle__short_lived_cell_ratio": -0.2649889849488947
          }
        ],
        "positive": [
          {
            "capacity__capacity_input_entropy": 0.399848594406167
          },
          {
            "capacity__capacity_output_entropy": 0.38115540701399925
          },
          {
            "lifecycle__consumed_cell_count": 0.2715979279810903
          }
        ]
      },
      "PC4": {
        "negative": [
          {
            "lifecycle__same_block_consumption_ratio": -0.4675251413466318
          },
          {
            "lifecycle__rapid_consumption_ratio": -0.37797081533384586
          },
          {
            "lifecycle__consumed_cell_count": -0.3448270651456376
          }
        ],
        "positive": [
          {
            "capacity__target_net_capacity_delta": 0.14992309967510936
          },
          {
            "lifecycle__long_lived_cell_ratio": 0.04795737130559555
          },
          {
            "capacity__capacity_input_entropy": -0.05967304021108185
          }
        ]
      },
      "PC5": {
        "negative": [
          {
            "capacity__capacity_repeat_ratio": -0.43722360324199977
          },
          {
            "capacity__target_net_capacity_delta": -0.36321131443055044
          },
          {
            "capacity__target_consumed_capacity": -0.28149925895788963
          }
        ],
        "positive": [
          {
            "lifecycle__same_block_consumption_ratio": 0.5833602580971549
          },
          {
            "lifecycle__rapid_consumption_ratio": 0.14257719473448227
          },
          {
            "lineage__branch_count": 0.1357345101332411
          }
        ]
      }
    },
    "variance_thresholds": {
      "0.5": 3,
      "0.7": 6,
      "0.8": 7,
      "0.9": 9,
      "0.95": 11
    },
    "wallets_per_feature": 9.555555555555555
  }
]
```

## M. Cross-experiment comparison

Valid experiments are compared by variance concentration, family contribution, activity association, and component stability. Different feature spaces are not expected to yield identical components.

## N. Recommended primary feature representation

Keep **High-Confidence** as the clean complete-case reference representation. Use the accepted Temporal and Cell blocks as complementary behavioural-coverage sensitivity experiments; do not replace the reference with the 28×59 Low-Redundancy matrix.

## O. Recommended next ML experiment

Retain the representation for the next sensitivity stage while continuing post-hoc activity audits.
Review PCA geometry and activity axes before defining any UMAP or clustering experiment.

## P. Readiness

- **PCA HIGH-CONFIDENCE: READY** — complete-case reference executed and stability measured.
- **PCA LOW-REDUNDANCY: NOT READY** — 28×59 fails the locked feasibility gate.
- **ACTIVITY-VOLUME CONTROL: READY** — diagnostics complete; separate control experiment required only if high association is present.
- **COMPONENT STABILITY: READY** — deterministic resampling completed.
- **PRIMARY FEATURE REPRESENTATION: READY** — High-Confidence remains the reference, with family blocks as sensitivity views.
- **UMAP: PARTIAL** — not executed; requires locked follow-up preprocessing.
- **HDBSCAN: NOT READY** — PCA geometry must inform a separate clustering contract.
- **GMM: NOT READY** — covariance/geometry suitability must be evaluated separately.
- **SUPERVISED CLASSIFICATION: NOT READY** — no defensible labels exist.

No UMAP, clustering, classification, collection, retry, identity interpretation, commit, merge, or push was performed.
