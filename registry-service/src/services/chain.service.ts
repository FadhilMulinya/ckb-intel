import { getChainTip } from "../clients/ckb.client.js";
import { config } from "../config/index.js";

/**
 * Service = logic. Chain-level status queries (connectivity, tip height).
 *
 * Cached for CACHE_TTL_MS: the tip block number doesn't need per-request
 * freshness, and getChainTip() is a real network round trip to the public
 * CKB RPC endpoint -- caching keeps repeated /chain/status calls (health
 * dashboards polling it, for example) fast instead of paying that latency
 * every single time.
 */

export interface ChainStatus {
  network: "mainnet";
  tipBlockNumber: number;
}

const CACHE_TTL_MS = 5000;
let cached: { status: ChainStatus; expiresAt: number } | null = null;

export async function getChainStatus(): Promise<ChainStatus> {
  if (cached && cached.expiresAt > Date.now()) {
    return cached.status;
  }
  const tipBlockNumber = await getChainTip();
  const status: ChainStatus = { network: config.network, tipBlockNumber };
  cached = { status, expiresAt: Date.now() + CACHE_TTL_MS };
  return status;
}
