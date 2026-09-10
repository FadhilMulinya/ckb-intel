from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .base import FEATURE_SCHEMA_VERSION, OBSERVATION_CONTRACT_VERSION, SupportState

RULE_VERSION = "ckb-transparent-rules-v1"


@dataclass
class BehaviourEvidence:
    pattern: str
    score: float | None
    support_state: SupportState
    reason_codes: list[str]
    feature_values: dict[str, Any]
    support: dict[str, Any]
    supporting_transactions: list[str]
    observation_contract_version: str = OBSERVATION_CONTRACT_VERSION
    feature_schema_version: str = FEATURE_SCHEMA_VERSION
    rule_version: str = RULE_VERSION

    def as_dict(self) -> dict:
        result = asdict(self)
        result["support_state"] = self.support_state.value
        return result
