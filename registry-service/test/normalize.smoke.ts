import { normalizeExplorerTx } from "../src/services/normalization.service.js";
import { ExplorerTxEntry } from "../src/clients/explorer.client.js";

// Real sample shape pulled from the CKB Explorer API docs
// (https://ckb-explorer.readme.io/reference/transactions-of-an-address)
const sample: ExplorerTxEntry = {
  id: "22659032",
  type: "ckb_transactions",
  attributes: {
    is_cellbase: true,
    transaction_hash:
      "0x3f3ac6309b052384519bafd212abb89d18b7beb544e05e664265bf1a78bbcbc3",
    block_number: "10569720",
    block_timestamp: "1690619510227",
    display_inputs_count: 1,
    display_outputs_count: 1,
    display_inputs: [
      {
        id: "",
        from_cellbase: true,
        capacity: "",
        address_hash: "",
        target_block_number: "10569709",
        generated_tx_hash:
          "0x3f3ac6309b052384519bafd212abb89d18b7beb544e05e664265bf1a78bbcbc3",
      },
    ],
    display_outputs: [
      {
        id: "42283325",
        capacity: "159670850145.0",
        address_hash:
          "ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsq0dn8gg6ag6uvkl0lr0xpyt0n99dsal47sm7mzyj",
        status: "live",
        consumed_tx_hash: "",
      },
    ],
    income: "159670850145.0",
  },
};

const walletAddress =
  "ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsq0dn8gg6ag6uvkl0lr0xpyt0n99dsal47sm7mzyj";

const result = normalizeExplorerTx(sample, walletAddress);

console.log(JSON.stringify(result, null, 2));

console.assert(result.txHash === sample.attributes.transaction_hash, "txHash mismatch");
console.assert(result.blockNumber === 10569720, "blockNumber mismatch");
console.assert(result.timestampMs === 1690619510227, "timestampMs mismatch");
console.assert(result.isCellbase === true, "isCellbase mismatch");
console.assert(result.outputs.length === 1, "outputs length mismatch");
console.assert(
  result.outputs[0].capacityShannon === "159670850145.0",
  "output capacity mismatch"
);
// Self address should be excluded from counterparties
console.assert(
  !result.counterpartyAddresses.includes(walletAddress),
  "self address leaked into counterparties"
);

console.log("\n✅ normalize.ts smoke test passed");
