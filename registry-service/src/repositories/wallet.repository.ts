import { Wallet, WalletProfile } from "../db/models/Wallet.js";

export async function upsert(profile: Record<string, any>): Promise<WalletProfile> {
  return Wallet.findOneAndUpdate(
    { address: profile.address },
    { address: profile.address, network: profile.network,
      analysisVersion: profile.version, observation: profile.observation,
      evidence: profile.evidence, featureSupport: profile.feature_support,
      features: profile.features, behaviors: profile.behaviors,
      limitations: profile.limitations },
    { upsert: true, new: true, setDefaultsOnInsert: true }
  );
}

export function response(value: WalletProfile): Record<string, unknown> {
  return {
    version: value.analysisVersion,
    address: value.address,
    network: value.network,
    observation: value.observation,
    evidence: value.evidence,
    feature_support: value.featureSupport,
    features: value.features,
    behaviors: value.behaviors,
    limitations: value.limitations,
    created_at: value.createdAt,
    updated_at: value.updatedAt,
  };
}

export async function find(address: string): Promise<WalletProfile | null> {
  return Wallet.findOne({ address });
}

export async function list(skip: number, limit: number): Promise<{ items: WalletProfile[]; total: number }> {
  const [items, total] = await Promise.all([
    Wallet.find().sort({ updatedAt: -1 }).skip(skip).limit(limit),
    Wallet.countDocuments(),
  ]);
  return { items, total };
}
