import { ExplorerTxEntry } from "../clients/explorer.client.js";
import { NormalizedCellRef, NormalizedTransaction } from "../types/index.js";

/**
 * Service = logic. Pure transformation from the Explorer API's raw shape
 * into our normalized schema. No I/O, no persistence — fully unit-testable.
 *
 * `walletAddress` is the address we ingested this tx for — used to figure
 * out which side of the tx is "us" vs. "counterparty" for the interaction
 * graph features later.
 */
export function normalizeExplorerTx(
  entry: ExplorerTxEntry,
  walletAddress: string
): NormalizedTransaction {
  const attrs = entry.attributes;

  const inputs: NormalizedCellRef[] = attrs.display_inputs.map((input, idx) => ({
    txHash: input.generated_tx_hash ?? "",
    index: idx,
    capacityShannon: input.capacity || "0",
    address: input.address_hash || undefined,
    cellKind: input.from_cellbase ? "cellbase" : "plain",
  }));

  const outputs: NormalizedCellRef[] = attrs.display_outputs.map((output, idx) => ({
    txHash: attrs.transaction_hash,
    index: idx,
    capacityShannon: output.capacity || "0",
    address: output.address_hash || undefined,
    cellKind: "plain",
  }));

  const counterpartyAddresses = Array.from(
    new Set(
      [...inputs, ...outputs]
        .map((c) => c.address)
        .filter((addr): addr is string => !!addr && addr !== walletAddress)
    )
  );

  return {
    txHash: attrs.transaction_hash,
    blockNumber: Number(attrs.block_number),
    timestampMs: Number(attrs.block_timestamp),
    inputs,
    outputs,
    counterpartyAddresses,
    isCellbase: attrs.is_cellbase,
  };
}
