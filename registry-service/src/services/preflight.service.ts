import { getChainTip } from "../clients/ckb.client.js";
import { explorerClient } from "../clients/explorer.client.js";
import { config } from "../config/index.js";

/**
 * Service = logic. Startup pre-flight: verifies every external dependency
 * is alive before the application is allowed to start. If any check fails,
 * the caller (server.ts) aborts instead of serving requests that are
 * guaranteed to fail later.
 */

export interface PreflightCheck {
  name: string;
  ok: boolean;
  detail: string;
}

async function checkCkbRpc(): Promise<PreflightCheck> {
  try {
    const tip = await getChainTip();
    return {
      name: "ckb-rpc (CCC)",
      ok: true,
      detail: `${config.network} tip block ${tip}`,
    };
  } catch (err) {
    return {
      name: "ckb-rpc (CCC)",
      ok: false,
      detail: (err as Error).message,
    };
  }
}

async function checkExplorerApi(): Promise<PreflightCheck> {
  try {
    await explorerClient.ping();
    return {
      name: "explorer-api",
      ok: true,
      detail: `reachable at ${config.explorerApiUrl}`,
    };
  } catch (err) {
    return {
      name: "explorer-api",
      ok: false,
      detail: (err as Error).message,
    };
  }
}

/** Run all external-dependency checks in parallel and report each result. */
export async function runPreflightChecks(): Promise<PreflightCheck[]> {
  return Promise.all([checkCkbRpc(), checkExplorerApi()]);
}

/**
 * Run the checks, log each one, and throw if any dependency is down.
 * Called by the API server before it starts listening.
 */
export async function assertExternalDependenciesAlive(): Promise<void> {
  console.log("[preflight] checking external dependencies...");
  const checks = await runPreflightChecks();

  for (const check of checks) {
    const mark = check.ok ? "✅" : "❌";
    console.log(`[preflight] ${mark} ${check.name}: ${check.detail}`);
  }

  const failed = checks.filter((c) => !c.ok);
  if (failed.length > 0) {
    throw new Error(
      `preflight failed — ${failed.map((c) => c.name).join(", ")} unreachable. ` +
        `Application will not start.`
    );
  }
}
