from __future__ import annotations

from . import temporal, templates, topology
from .rules import batch_distribution, fan_in_collection, periodic_execution


def assess_observation(observation: dict) -> dict:
    temporal_result = temporal.extract(observation)
    topology_result = topology.extract(observation)
    template_result = templates.extract(observation)
    assessments = [periodic_execution(observation, temporal_result),
                   batch_distribution(observation, topology_result, template_result),
                   fan_in_collection(observation, topology_result, template_result)]
    return {"features": {"temporal": temporal_result.as_dict(),
                         "topology": topology_result.as_dict(),
                         "templates": template_result.as_dict()},
            "assessments": [assessment.as_dict() for assessment in assessments]}
