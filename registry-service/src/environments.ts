import dotenv from "dotenv";
dotenv.config();

function required(name: string, fallback?: string): string {
  const val = process.env[name] ?? fallback;
  if (val === undefined) {
    throw new Error(`Missing required env var: ${name}`);
  }
  return val;
}

export function positiveInteger(name: string, fallback: number): number {
  const value = Number(process.env[name] ?? fallback);
  if (!Number.isSafeInteger(value) || value < 1) throw new Error(`${name} must be a positive integer`);
  return value;
}

export function allowedOrigins(value: string): string[] {
  return [...new Set(value.split(",").map(origin => origin.trim()).filter(Boolean).map(origin => {
    const url = new URL(origin);
    if (!["https:", "http:"].includes(url.protocol) || url.origin !== origin || url.hostname.includes("*")) {
      throw new Error("CORS_ALLOWED_ORIGINS must contain exact HTTP(S) origins without paths or wildcards");
    }
    return origin;
  }))];
}

export const environments = {
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
  mongodbUri: process.env.MONGODB_URI ?? "",
  explorerPageSize: Number(process.env.EXPLORER_PAGE_SIZE ?? 50),
  requestDelayMs: Number(process.env.REQUEST_DELAY_MS ?? 250),
  maxTxPerWallet: Number(process.env.MAX_TX_PER_WALLET ?? 2000),
  apiPort: Number(process.env.API_PORT ?? 3000),
  apiHost: process.env.API_HOST ?? "0.0.0.0",
  classifierServiceUrl: process.env.CLASSIFIER_SERVICE_URL ?? "http://127.0.0.1:8000",
  classifierTimeoutMs: positiveInteger("CLASSIFIER_TIMEOUT_MS", 20000),
  corsAllowedOrigins: allowedOrigins(process.env.CORS_ALLOWED_ORIGINS ?? "https://demo.afriai.xyz,https://afriai.xyz, https://api.afriai.xyz"),
  // Only explicitly listed immediate proxy addresses are trusted. Empty = none.
  trustedProxies: (process.env.TRUSTED_PROXY_CIDRS ?? "").split(",").map(value => value.trim()).filter(Boolean),
  analyzeRateLimit: positiveInteger("ANALYZE_RATE_LIMIT", 5),
  analyzeRateWindowMs: positiveInteger("ANALYZE_RATE_WINDOW_SECONDS", 60) * 1000,
  readRateLimit: positiveInteger("READ_RATE_LIMIT", 60),
  readRateWindowMs: positiveInteger("READ_RATE_WINDOW_SECONDS", 60) * 1000,
  // Retained for compatibility with existing deployment environment files.
  ingestWindowStart: process.env.INGEST_WINDOW_START ?? "2025-06-01T00:00:00Z",
  ingestWindowEnd: process.env.INGEST_WINDOW_END ?? "2026-06-30T23:59:59.999Z",
};
