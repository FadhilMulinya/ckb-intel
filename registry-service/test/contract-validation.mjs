import assert from "node:assert/strict";
import { validateCkbAddress } from "../dist/ckbaddressvalidator.js";
import { validateProfile, ContractError } from "../dist/contract/profile.js";

const address = "ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsqg239ffgrtl3mf4m6s02eweangtpe0gy9cph6u05";
assert.equal(await validateCkbAddress(address), true);
assert.equal(await validateCkbAddress("ckb1invalid"), false);

const families = ["temporal", "periodicity", "topology", "lifecycle", "templates", "scripts", "typed_assets", "capacity", "lineage"];
const features = Object.fromEntries(families.map((family) => [family, {
  feature_family: family, support_state: "SUPPORTED", requirements: {}, sample_count: 1,
  coverage: {}, values: {}, evidence: {}, feature_schema_version: "x", dataset_version: "x", observation_contract_version: "x",
}]));
const profile = { version: "wallet-behaviour-v2", address, network: "mainnet", observation: {}, evidence: {}, feature_support: Object.fromEntries(families.map((f) => [f, "SUPPORTED"])), features, behaviors: [{ rule: "MIXED", support_state: "SUPPORTED", score: null, reason_codes: [], supporting_features: {}, supporting_transaction_hashes: [], supporting_transaction_count: 0, rule_version: "x" }], limitations: [] };
assert.equal(await validateProfile(profile), profile);
for (const malformed of [
  { ...profile, version: "wrong" },
  { ...profile, limitations: "missing-array" },
  { ...profile, features: { ...features, temporal: { ...features.temporal, support_state: "BROKEN" } } },
  { ...profile, bot_probability: 0.5 },
]) await assert.rejects(() => validateProfile(malformed), ContractError);
console.log("contract validation tests passed");
