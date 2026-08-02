/**
 * Normalized schema that both the CCC client and the Explorer client
 * map their raw responses into. This is the shape everything downstream
 * (Mongo, feature engineering) should depend on — not on either API's
 * native response format.
 */

export interface NormalizedCellRef {
  txHash: string;
  index: number;
  capacityShannon: string; // keep as string, capacities can exceed Number safe range
  // CKB address string (ckb1.../ckt1...) of the cell's owner. The Explorer
  // API exposes owners as addresses, not lock script hashes — name it what
  // it is. (The wallet-level lockScriptHash, resolved via CCC, IS a 0x hash.)
  address?: string;
  typeScriptHash?: string;
  // "sudt", "nft", "dao", "plain" etc. Best-effort classification, refined later.
  cellKind?: string;
}

export interface NormalizedTransaction {
  txHash: string;
  blockNumber?: number;
  // Explorer gives block timestamp in ms; keep as epoch ms throughout.
  timestampMs: number;
  inputs: NormalizedCellRef[];
  outputs: NormalizedCellRef[];
  // Addresses involved on the "other side" of this tx relative to the
  // wallet being ingested. Folded into the ingestion counters, never
  // persisted -- see ingestion.service.ts.
  counterpartyAddresses: string[];
  feeShannon?: string;
  isCellbase?: boolean;
}
