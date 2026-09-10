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
  explorerApiUrl: required(
    "EXPLORER_API_URL_MAINNET",
    "https://mainnet-api.explorer.nervos.org/api/v1"
  ),
  mongodbUri: required("MONGODB_URI", "mongodb://localhost:27017/behaviour-intelligence"),
  explorerPageSize: Number(process.env.EXPLORER_PAGE_SIZE ?? 50),
  requestDelayMs: Number(process.env.REQUEST_DELAY_MS ?? 250),
  maxTxPerWallet: Number(process.env.MAX_TX_PER_WALLET ?? 2000),
  apiPort: Number(process.env.API_PORT ?? 3000),
  apiHost: process.env.API_HOST ?? "0.0.0.0",
  classifierServiceUrl: process.env.CLASSIFIER_SERVICE_URL ?? "http://127.0.0.1:8000",
  classifierTimeoutMs: Number(process.env.CLASSIFIER_TIMEOUT_MS ?? 20000),
  // Retained for compatibility with existing deployment environment files.
  ingestWindowStart: process.env.INGEST_WINDOW_START ?? "2025-06-01T00:00:00Z",
  ingestWindowEnd: process.env.INGEST_WINDOW_END ?? "2026-06-30T23:59:59.999Z",
};
