import { Address, ClientPublicMainnet } from "@ckb-ccc/core";

const mainnetClient = new ClientPublicMainnet();

/** Validate a canonical lowercase CKB mainnet address with CCC. */
export async function validateCkbAddress(address: unknown): Promise<boolean> {
  if (typeof address !== "string" || address.length === 0 || address !== address.toLowerCase()) return false;
  if (!address.startsWith("ckb1")) return false;
  try {
    const parsed = await Address.fromString(address, mainnetClient);
    return parsed.prefix === "ckb";
  } catch {
    return false;
  }
}
