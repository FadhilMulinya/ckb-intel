import { ccc } from "@ckb-ccc/core";

/**
 * Thin wrapper around @ckb-ccc/core's Client.
 *
 * Role in the pipeline: CCC talks directly to a CKB RPC node. We use it for
 * the two things the Explorer API doesn't give us for free:
 *  - resolving an address string -> lock script -> lock script hash
 *    (the canonical key we use to identify a "wallet" internally, since one
 *    wallet can technically be represented by more than one address string)
 *  - sanity-checking chain tip / connectivity (preflight, /chain/status)
 *
 * The heavy lifting of "give me this wallet's transaction history" is left
 * to the Explorer client (src/clients/explorer.client.ts) since it's
 * already indexed there and far cheaper than replaying the chain ourselves.
 *
 * Mainnet only, always -- this project's data provenance guarantee (root
 * README §6) requires real mainnet data exclusively, so there is no
 * testnet client path here. Uses CCC's default public mainnet RPC
 * endpoint; there's currently no config override for the RPC URL itself
 * (see config/index.ts).
 */

let client: ccc.ClientPublicMainnet | null = null;

export function getCkbClient(): ccc.ClientPublicMainnet {
  if (client) return client;
  client = new ccc.ClientPublicMainnet();
  return client;
}

export interface ResolvedAddress {
  address: string;
  lockScriptHash: string;
  lockScript: {
    codeHash: string;
    hashType: string;
    args: string;
  };
}

/**
 * Parse a CKB address string into its lock script and lock script hash.
 * Throws if the address is malformed or belongs to the wrong network.
 */
export async function resolveAddress(address: string): Promise<ResolvedAddress> {
  const client = getCkbClient();
  const parsed = await ccc.Address.fromString(address, client);
  const lockScriptHash = parsed.script.hash();

  return {
    address,
    lockScriptHash,
    lockScript: {
      codeHash: parsed.script.codeHash,
      hashType: parsed.script.hashType,
      args: parsed.script.args,
    },
  };
}

/** Basic connectivity / sanity check, useful for a `--check` CLI flag. */
export async function getChainTip(): Promise<number> {
  const client = getCkbClient();
  const tipHeader = await client.getTipHeader();
  return Number(tipHeader.number);
}
