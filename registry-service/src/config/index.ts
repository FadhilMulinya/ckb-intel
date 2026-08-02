import dotenv from "dotenv";
dotenv.config();

function required(name: string, fallback?: string): string {
  const val = process.env[name] ?? fallback;
  if (val === undefined) {
    throw new Error(`Missing required env var: ${name}`);
  }
  return val;
}

export const config = {
  // Mainnet only -- this project's data provenance guarantee (see root
  // README §6 / REPORT.md §2) requires real mainnet data exclusively.
  // There used to be a CKB_NETWORK env var here that silently defaulted
  // to "testnet" when unset -- that was a real bug (the whole system
  // would run against testnet unless someone remembered to set it), not
  // a supported mode, so it's gone rather than fixed.
  network: "mainnet" as const,
  // No ckbRpcUrl here: getCkbClient() (src/clients/ckb.client.ts) uses
  // @ckb-ccc/core's ClientPublicMainnet(), which picks its own default
  // mainnet RPC endpoint internally -- there's currently no way to
  // override it via config, so we don't pretend one exists.
  explorerApiUrl: required(
    "EXPLORER_API_URL_MAINNET",
    "https://mainnet-api.explorer.nervos.org/api/v1"
  ),
  mongodbUri: required("MONGODB_URI", "mongodb://localhost:27017/ckb_wallet_intel"),
  explorerPageSize: Number(process.env.EXPLORER_PAGE_SIZE ?? 50),
  requestDelayMs: Number(process.env.REQUEST_DELAY_MS ?? 250),
  maxTxPerWallet: Number(process.env.MAX_TX_PER_WALLET ?? 2000),
  apiPort: Number(process.env.API_PORT ?? 3000),
  apiHost: process.env.API_HOST ?? "0.0.0.0",
  // Training-data time window (interpreted by services/time-window.service.ts).
  ingestWindowStart: process.env.INGEST_WINDOW_START ?? "2025-06-01T00:00:00Z",
  ingestWindowEnd: process.env.INGEST_WINDOW_END ?? "2026-06-30T23:59:59.999Z",
};
