FEATURE_SCHEMA_VERSION = "ckb-behaviour-features-v2"
FEATURE_CONFIG_VERSION = "ckb-behaviour-feature-config-v2"
DATASET_VERSION = "ckb-behaviour-dataset-v1"
OBSERVATION_CONTRACT_VERSION = "wallet-observation-30d-v1"
SCRIPT_REGISTRY_VERSION = "ckb-script-registry-v2"
RULE_VERSION = "ckb-behaviour-rules-v2"

RAPID_CELL_SECONDS = 300
SHORT_CELL_SECONDS = 3600
LONG_CELL_SECONDS = 86400
SESSION_GAP_SECONDS = 1800
BURST_GAP_SECONDS = 60
BURST_MIN_TRANSACTIONS = 3
REPEAT_TOLERANCE = 0.05

DURATION_BINS_SECONDS = (60, 300, 3600, 21600, 86400, 604800)

MINIMUM_SAMPLES = {
    "temporal": 5,
    "periodicity": 8,
    "lifecycle": 3,
    "topology": 3,
    "templates": 3,
    "scripts": 1,
    "typed_assets": 3,
    "capacity": 1,
    "lineage": 3,
}

RULE_THRESHOLDS = {
    "PERIODIC_EXECUTION": {"periodicity_strength": 0.80, "phase_stability": 0.75,
                           "maximum_interarrival_cv": 0.35},
    "BATCH_DISTRIBUTION": {"one_to_many_ratio": 0.50,
                           "external_output_lock_mean": 2.0,
                           "template_repeat_ratio": 0.50},
    "FAN_IN_COLLECTION": {"many_to_one_ratio": 0.50,
                          "external_input_lock_mean": 2.0,
                          "topology_repeat_ratio": 0.50},
    "BURST_EXECUTION": {"burst_count": 2, "transactions_in_bursts_ratio": 0.50},
    "CELL_FRAGMENTATION": {"event_ratio": 0.30, "mean_factor": 2.0},
    "CELL_CONSOLIDATION": {"event_ratio": 0.30, "mean_factor": 2.0},
    "SCRIPT_TEMPLATE_REPETITION": {"template_repeat_ratio": 0.50,
                                   "dominant_template_ratio": 0.30},
    "RAPID_CELL_TURNOVER": {"rapid_consumption_ratio": 0.50},
    "PASS_THROUGH_CANDIDATE": {"rapid_consumption_ratio": 0.50,
                               "continuation_ratio": 0.50,
                               "maximum_capacity_delta_ratio": 0.05},
    "STATE_MACHINE_ACTIVITY": {"minimum_transactions": 10,
                               "maximum_dominant_templates": 3,
                               "dominant_template_coverage": 0.80,
                               "transition_repeat_ratio": 0.60,
                               "maximum_transition_entropy": 0.50},
    "IRREGULAR_ACTIVITY": {"minimum_transactions": 8,
                           "maximum_periodicity_strength": 0.30,
                           "gap_entropy": 0.70,
                           "maximum_template_repeat_ratio": 0.30},
}

