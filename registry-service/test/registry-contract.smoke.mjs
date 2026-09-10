import { readFileSync } from "node:fs";

const routes = readFileSync("src/routes/index.ts", "utf8");
const service = readFileSync("src/services/registry.service.ts", "utf8");
const contract = readFileSync("src/contract/profile.ts", "utf8");
const server = readFileSync("src/server.ts", "utf8");
for (const path of ["/health", "/wallets/analyze", "/wallets", "/wallets/:address", "/wallets/:address/behaviors", "/wallets/:address/features"]) {
  if (!routes.includes(path)) throw new Error(`missing route ${path}`);
}
if (!contract.includes("wallet-behaviour-v2")) throw new Error("classifier contract is not validated");
if (!server.includes('prefix: "/api/v1"')) throw new Error("registry API must be mounted under /api/v1");
if (server.includes("/api/v2")) throw new Error("registry must not expose an /api/v2 surface");
for (const forbidden of ["human_like", "bot_like", "is_special", "bot_probability", "human_probability"]) {
  if (!contract.includes(forbidden)) throw new Error(`missing rejection guard for ${forbidden}`);
}
console.log("registry contract smoke test passed");
