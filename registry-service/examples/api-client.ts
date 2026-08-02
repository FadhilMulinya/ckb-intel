/**
 * Sample integration against the CKB Wallet Behaviour Intelligence REST API.
 *
 * Shows the typical consumer flow end to end:
 *   1. health check
 *   2. chain status (proves the service can reach the CKB network)
 *   3. submit an address for ingestion (wallet identity only -- no
 *      transaction data gets stored)
 *   4. read the wallet summary back
 *   5. write back a classification label (this is what
 *      classifier-service/predict.py does after scoring a wallet)
 *   6. list wallets filtered by that label
 *
 * Run it (with the API already running via `npm start`):
 *   npx tsx examples/api-client.ts <ckb-address>
 *
 * Uses only global fetch — copy/paste this into any Node 18+ or browser
 * project to integrate.
 */

const API_BASE = process.env.API_BASE ?? "http://localhost:3000/api/v1";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`GET ${path} -> ${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`POST ${path} -> ${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`PATCH ${path} -> ${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

async function main() {
  const address = process.argv[2];
  if (!address) {
    console.error("Usage: npx tsx examples/api-client.ts <ckb-address>");
    process.exit(1);
  }

  // 1. Is the API up?
  console.log("health:", await get("/health"));

  // 2. Can it reach the CKB network?
  console.log("chain status:", await get("/chain/status"));

  // 3. Ingest the wallet (identity only -- transactions are never stored,
  //    just used server-side to compute txCount/firstSeenMs/lastSeenMs).
  console.log(`ingesting ${address} ...`);
  const ingest = await post<{ requested: number; results: unknown[] }>("/ingest", {
    addresses: [address],
  });
  console.log("ingest result:", JSON.stringify(ingest, null, 2));

  // 4. Read the wallet summary back.
  const wallet = await get(`/wallets/${address}`);
  console.log("wallet summary:", JSON.stringify(wallet, null, 2));

  // 5. Write back a classification. In the real pipeline this call comes
  //    from classifier-service/predict.py after it fetches the wallet's history
  //    from Explorer directly and scores it -- label/botProbability here
  //    are exactly its `verdict`/`bot_probability` output fields.
  const labeled = await patch(`/wallets/${address}/label`, {
    label: "human",
    botProbability: 0.12,
  });
  console.log("labeled:", JSON.stringify(labeled, null, 2));

  // 6. List wallets carrying that label.
  const humans = await get<{ total: number; items: unknown[] }>("/wallets?label=human");
  console.log(`wallets labeled "human" (${humans.total} total, showing ${humans.items.length}):`);
  console.log(JSON.stringify(humans.items, null, 2));
}

main().catch((err) => {
  console.error("[example failed]", err.message);
  process.exit(1);
});
