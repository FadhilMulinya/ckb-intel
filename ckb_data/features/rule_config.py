
RULE_CONFIG_VERSION = "ckb-rule-thresholds-v1"

THRESHOLDS = {
    "PERIODIC_EXECUTION": {"minimum_transactions": 8, "periodicity_strength": 0.80,
                           "phase_stability": 0.75, "maximum_interarrival_cv": 0.35},
    "BATCH_DISTRIBUTION": {"minimum_transactions": 3, "fanout_transaction_ratio": 0.50,
                           "minimum_external_output_locks": 2.0,
                           "minimum_template_repeat_ratio": 0.50},
    "FAN_IN_COLLECTION": {"minimum_transactions": 3, "fanin_transaction_ratio": 0.50,
                          "minimum_external_input_locks": 2.0,
                          "minimum_topology_repeat_ratio": 0.50},
}
