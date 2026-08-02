import { resolveAddress } from "../clients/ckb.client.js";
import { explorerClient } from "../clients/explorer.client.js";
import { normalizeExplorerTx } from "./normalization.service.js";
import * as walletRepository from "../repositories/wallet.repository.js";
import { config } from "../config/index.js";
import {
  getIngestionWindow,
  isWithinWindow,
  isAfterWindow,
  isBeforeWindow,
  describeWindow,
} from "./time-window.service.js";

/**
 * Service = logic. Orchestrates a wallet ingestion end to end:
 *  1. Resolve the address on-chain via CCC to get its canonical lock script hash.
 *  2. Page through its transaction history via the Explorer API, newest
 *     first, keeping only transactions inside the training time window
 *     (see time-window.service.ts) and stopping as soon as paging moves
 *     past the window — full histories are never traversed.
 *  3. Normalize each in-window transaction just long enough to fold it into
 *     the running tx-count/first-seen/last-seen counters below -- normalized
 *     transactions are never persisted (this service is wallet-identity-only;
 *     no Transaction collection exists).
 *  4. Update the wallet's summary doc (tx count, first/last seen, status).
 *
 * Talks to clients (external world) and repositories (data) — never to
 * Mongoose or HTTP directly.
 *
 * Idempotent: re-running for the same address just upserts, so it's safe
 * to re-ingest wallets to pick up new activity.
 */

export interface IngestSummary {
  address: string;
  lockScriptHash: string;
  txIngested: number;
  firstSeenMs?: number;
  lastSeenMs?: number;
}

export async function ingestWallet(address: string): Promise<IngestSummary> {
  const window = getIngestionWindow();
  console.log(
    `[ingest] resolving address: ${address} (window ${describeWindow(window)})`
  );
  const resolved = await resolveAddress(address);

  await walletRepository.upsertWallet({
    address,
    lockScriptHash: resolved.lockScriptHash,
    network: config.network,
  });

  let count = 0;
  let firstSeenMs: number | undefined;
  let lastSeenMs: number | undefined;

  try {
    // Newest-first so we can stop paging at the first tx older than the window.
    for await (const entry of explorerClient.iterateAddressTransactions(
      address,
      config.maxTxPerWallet,
      "time.desc"
    )) {
      const timestampMs = Number(entry.attributes.block_timestamp);

      if (isAfterWindow(timestampMs, window)) continue; // too recent, keep paging back
      if (isBeforeWindow(timestampMs, window)) {
        console.log(`[ingest] ${address}: reached txs older than window, stopping`);
        break; // desc order — everything from here on is older, stop entirely
      }
      if (!isWithinWindow(timestampMs, window)) continue; // defensive; unreachable

      const normalized = normalizeExplorerTx(entry, address);

      firstSeenMs =
        firstSeenMs === undefined
          ? normalized.timestampMs
          : Math.min(firstSeenMs, normalized.timestampMs);
      lastSeenMs =
        lastSeenMs === undefined
          ? normalized.timestampMs
          : Math.max(lastSeenMs, normalized.timestampMs);

      count += 1;
      if (count % 100 === 0) {
        console.log(`[ingest] ${address}: ${count} transactions so far...`);
      }
    }

    await walletRepository.updateIngestionResult(address, {
      txCount: count,
      firstSeenMs,
      lastSeenMs,
      ingestionStatus: "complete",
      lastIngestedAt: new Date(),
    });

    console.log(`[ingest] done: ${address} -> ${count} transactions`);
  } catch (err) {
    await walletRepository.markIngestionFailed(address);
    throw err;
  }

  return {
    address,
    lockScriptHash: resolved.lockScriptHash,
    txIngested: count,
    firstSeenMs,
    lastSeenMs,
  };
}

/** Ingest a batch of addresses sequentially (kept simple/polite to the public API). */
export async function ingestWallets(addresses: string[]): Promise<IngestSummary[]> {
  const results: IngestSummary[] = [];
  for (const address of addresses) {
    try {
      results.push(await ingestWallet(address));
    } catch (err) {
      console.error(`[ingest] failed for ${address}:`, (err as Error).message);
    }
  }
  return results;
}
