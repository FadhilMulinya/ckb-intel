import { validateCkbAddress } from "../ckbaddressvalidator.js";

export const VERSION = "wallet-behaviour-v2" as const;
export const NETWORK = "mainnet" as const;
export const FEATURE_FAMILIES = [
  "temporal", "periodicity", "topology", "lifecycle", "templates",
  "scripts", "typed_assets", "capacity", "lineage",
] as const;

export const SUPPORT_STATES = ["SUPPORTED", "PARTIAL", "INSUFFICIENT_EVIDENCE", "UNRESOLVED"] as const;

const FORBIDDEN = new Set([
  "human_like", "bot_like", "is_special", "bot_probability", "human_probability",
  "classifier_confidence", "identity_class", "predicted_class", "wallet_identity",
]);

export class ContractError extends Error {
  status = "INVALID_ANALYSIS_RESPONSE" as const;
}

function object(value: unknown, name: string): Record<string, any> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new ContractError(`${name} must be an object`);
  return value as Record<string, any>;
}

function string(value: unknown, name: string): string {
  if (typeof value !== "string" || value.length === 0) throw new ContractError(`${name} must be a non-empty string`);
  return value;
}

function nullableNumber(value: unknown, name: string): void {
  if (value !== null && typeof value !== "number") throw new ContractError(`${name} must be a number or null`);
}

function hasForbidden(value: unknown): boolean {
  if (Array.isArray(value)) return value.some(hasForbidden);
  if (!value || typeof value !== "object") return false;
  return Object.entries(value).some(([key, item]) => FORBIDDEN.has(key) || hasForbidden(item));
}

export async function validateProfile(value: unknown): Promise<Record<string, any>> {
  const profile = object(value, "profile");
  for (const key of ["version", "address", "network", "observation", "evidence", "feature_support", "features", "behaviors", "limitations"]) {
    if (!(key in profile)) throw new ContractError(`missing ${key}`);
  }
  if (profile.version !== VERSION) throw new ContractError("unsupported analysis contract");
  if (profile.network !== NETWORK) throw new ContractError("unsupported network");
  if (!(await validateCkbAddress(profile.address))) throw new ContractError("invalid profile address");
  object(profile.observation, "observation");
  object(profile.evidence, "evidence");
  const support = object(profile.feature_support, "feature_support");
  const features = object(profile.features, "features");
  for (const family of FEATURE_FAMILIES) {
    const feature = object(features[family], `features.${family}`);
    for (const key of ["feature_family", "support_state", "requirements", "sample_count", "coverage", "values", "evidence", "feature_schema_version", "dataset_version", "observation_contract_version"]) {
      if (!(key in feature)) throw new ContractError(`missing features.${family}.${key}`);
    }
    if (feature.feature_family !== family || !SUPPORT_STATES.includes(feature.support_state)) throw new ContractError(`invalid features.${family}`);
    if (!Number.isInteger(feature.sample_count) || feature.sample_count < 0) throw new ContractError(`invalid features.${family}.sample_count`);
    object(feature.requirements, `features.${family}.requirements`); object(feature.coverage, `features.${family}.coverage`);
    object(feature.values, `features.${family}.values`); object(feature.evidence, `features.${family}.evidence`);
    if (support[family] !== feature.support_state) throw new ContractError(`feature support mismatch for ${family}`);
  }
  if (!Array.isArray(profile.behaviors)) throw new ContractError("behaviors must be an array");
  for (const [index, behaviorValue] of profile.behaviors.entries()) {
    const behavior = object(behaviorValue, `behaviors[${index}]`);
    for (const key of ["rule", "support_state", "score", "reason_codes", "supporting_features", "supporting_transaction_hashes", "supporting_transaction_count", "rule_version"]) if (!(key in behavior)) throw new ContractError(`missing behaviors[${index}].${key}`);
    string(behavior.rule, `behaviors[${index}].rule`);
    if (!SUPPORT_STATES.includes(behavior.support_state)) throw new ContractError(`invalid behaviors[${index}].support_state`);
    nullableNumber(behavior.score, `behaviors[${index}].score`);
    if (!Array.isArray(behavior.reason_codes) || !Array.isArray(behavior.supporting_transaction_hashes) || !Number.isInteger(behavior.supporting_transaction_count)) throw new ContractError(`invalid behaviors[${index}]`);
    object(behavior.supporting_features, `behaviors[${index}].supporting_features`);
  }
  if (!Array.isArray(profile.limitations) || profile.limitations.some((item: unknown) => typeof item !== "string")) throw new ContractError("limitations must be an array of strings");
  if (hasForbidden(profile)) throw new ContractError("forbidden identity field in analysis response");
  return profile;
}
