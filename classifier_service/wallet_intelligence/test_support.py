"""Shared deterministic fixtures for normalization and service tests."""

LOCK_A = {"code_hash": "0x" + "11" * 32, "hash_type": "type", "args": "0xaaaa"}
LOCK_B = {"code_hash": "0x" + "22" * 32, "hash_type": "type", "args": "0xbbbb"}
LOCK_C = {"code_hash": "0x" + "33" * 32, "hash_type": "type", "args": "0xcccc"}
TYPE_X = {"code_hash": "0x" + "44" * 32, "hash_type": "type", "args": "0x1234"}


def cell(capacity, lock, *, tx="0xprev", index=0, type_script=None, data="0x"):
    return {"capacity": str(capacity), "lock": lock, "type": type_script,
            "output_data": data,
            "previous_output": {"tx_hash": tx, "index": index}}


def payload(inputs, outputs, fee=None, tx_hash="0xtx"):
    attrs = {"transaction_hash": tx_hash, "block_number": "100",
             "block_timestamp": "1700000000000", "transaction_index": "2",
             "display_inputs": inputs, "display_outputs": outputs}
    if fee is not None:
        attrs["transaction_fee"] = str(fee)
    return {"data": {"id": tx_hash, "attributes": attrs}}
