from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from .config import DATASET_VERSION, FEATURE_SCHEMA_VERSION, OBSERVATION_CONTRACT_VERSION


class SupportState(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNRESOLVED = "UNRESOLVED"


@dataclass
class FeatureResultV2:
    feature_family: str
    support_state: SupportState
    requirements: dict[str, Any]
    sample_count: int
    coverage: dict[str, Any]
    values: dict[str, Any]
    evidence: dict[str, Any]
    feature_schema_version: str = FEATURE_SCHEMA_VERSION
    dataset_version: str = DATASET_VERSION
    observation_contract_version: str = OBSERVATION_CONTRACT_VERSION

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["support_state"] = self.support_state.value
        return result


def family_support(observation: dict, sample_count: int, minimum: int,
                   *, require_details: bool = False,
                   require_inputs: bool = False,
                   coverage_complete: bool = True) -> SupportState:
    metadata = observation.get("metadata") or {}
    if metadata.get("collection_state") == "FAILED_INVALID_ADDRESS":
        return SupportState.UNRESOLVED
    if sample_count < minimum:
        return SupportState.INSUFFICIENT_EVIDENCE
    if require_details and metadata.get("detail_complete") is False:
        return SupportState.PARTIAL
    if require_inputs and metadata.get("input_resolution_complete") is False:
        return SupportState.PARTIAL
    if not coverage_complete:
        return SupportState.PARTIAL
    return SupportState.SUPPORTED


def empty_result(family: str, state: SupportState, requirements: dict,
                 sample_count: int, names: list[str], evidence: dict | None = None,
                 coverage: dict | None = None) -> FeatureResultV2:
    return FeatureResultV2(family, state, requirements, sample_count,
                           coverage or {}, {name: None for name in names},
                           evidence or {})

