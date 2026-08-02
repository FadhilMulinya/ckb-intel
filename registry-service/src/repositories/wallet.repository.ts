import { Wallet, WalletDoc, WalletLabel } from "../db/models/Wallet.js";

/**
 * Repository = data. All Wallet collection access goes through here.
 * No business decisions are made in this file — callers (services) decide
 * *when* and *why* to persist; this file only knows *how*.
 */

export interface WalletUpsertInput {
  address: string;
  lockScriptHash: string;
  network: "mainnet";
}

export interface WalletIngestionUpdate {
  txCount: number;
  firstSeenMs?: number;
  lastSeenMs?: number;
  ingestionStatus: "complete" | "failed";
  lastIngestedAt?: Date;
}

export interface WalletLabelUpdate {
  label: WalletLabel;
  botProbability: number | null;
  classifiedAt: Date;
}

export async function upsertWallet(input: WalletUpsertInput): Promise<WalletDoc> {
  return Wallet.findOneAndUpdate(
    { address: input.address },
    { ...input, ingestionStatus: "in_progress" },
    { upsert: true, new: true, setDefaultsOnInsert: true }
  );
}

export async function updateIngestionResult(
  address: string,
  update: WalletIngestionUpdate
): Promise<void> {
  await Wallet.findOneAndUpdate({ address }, update);
}

export async function markIngestionFailed(address: string): Promise<void> {
  await Wallet.findOneAndUpdate({ address }, { ingestionStatus: "failed" });
}

export async function findWalletByAddress(address: string): Promise<WalletDoc | null> {
  return Wallet.findOne({ address });
}

export async function listWallets(
  limit = 50,
  skip = 0,
  label?: WalletLabel
): Promise<WalletDoc[]> {
  return Wallet.find(label ? { label } : {})
    .sort({ updatedAt: -1 })
    .skip(skip)
    .limit(limit);
}

export async function countWallets(label?: WalletLabel): Promise<number> {
  return Wallet.countDocuments(label ? { label } : {});
}

// Auto-creates the wallet record if it doesn't exist yet -- a label can
// arrive (from classifier-service/predict.py) for an address that was never
// ingested, or whose ingestion failed/hasn't run. Identity fields
// (lockScriptHash/network) simply stay unset in that case until/unless
// POST /ingest later fills them in via its own upsert.
export async function updateLabel(
  address: string,
  update: WalletLabelUpdate
): Promise<WalletDoc> {
  return Wallet.findOneAndUpdate(
    { address },
    { address, ...update },
    { upsert: true, new: true, setDefaultsOnInsert: true }
  );
}
