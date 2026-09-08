#!/usr/bin/env python3
"""Debug script to inspect enriched transaction data."""

import json
import sqlite3
from inference_service import CKBDataCollector
from pathlib import Path

def main():
    # Test wallet from metadata
    address = "ckb1qrgqep8saj8agswr30pls73hra28ry8jlnlc3ejzh3dl2ju7xxpjxqgqqyjw0y2p7ahcysl4qhq97x60svqn29492qpkvy2s"
    
    # Connect to database
    db_path = "ckb_data/ckb-behaviour-dataset-v1.sqlite"
    collector = CKBDataCollector(db_path=Path(db_path))
    collector.connect()
    
    print(f"Fetching transactions for: {address}\n")
    txs = collector.fetch_wallet_transactions_cached(address)
    
    print(f"Total transactions: {len(txs)}\n")
    
    # Inspect first transaction in detail
    if txs:
        first_tx = txs[0]
        print(f"=== First Transaction ===")
        print(f"tx_hash: {first_tx.get('tx_hash')}")
        print(f"Inputs: {len(first_tx.get('inputs', []))}")
        print(f"Outputs: {len(first_tx.get('outputs', []))}\n")
        
        # Inspect first input
        if first_tx.get('inputs'):
            print("=== First Input ===")
            inp = first_tx['inputs'][0]
            print(f"Keys: {list(inp.keys())}")
            print(f"resolved_lock_script_hash: {inp.get('resolved_lock_script_hash')}")
            print(f"resolved_type_script_hash: {inp.get('resolved_type_script_hash')}")
            print(f"lock_script: {inp.get('lock_script')}")
            print(f"type_script: {inp.get('type_script')}\n")
        
        # Inspect first output
        if first_tx.get('outputs'):
            print("=== First Output ===")
            out = first_tx['outputs'][0]
            print(f"Keys: {list(out.keys())}")
            print(f"lock_script_hash: {out.get('lock_script_hash')}")
            print(f"type_script_hash: {out.get('type_script_hash')}")
            print(f"lock_script: {out.get('lock_script')}")
            print(f"type_script: {out.get('type_script')}\n")
        
        # Count scripts across all txs
        lock_code_hashes_from_inputs = set()
        lock_code_hashes_from_outputs = set()
        type_code_hashes_from_outputs = set()
        
        for tx in txs:
            for inp in tx.get('inputs', []):
                if inp.get('lock_script') and inp['lock_script'].get('code_hash'):
                    lock_code_hashes_from_inputs.add(inp['lock_script']['code_hash'][:16])
            
            for out in tx.get('outputs', []):
                if out.get('lock_script') and out['lock_script'].get('code_hash'):
                    lock_code_hashes_from_outputs.add(out['lock_script']['code_hash'][:16])
                if out.get('type_script') and out['type_script'].get('code_hash'):
                    type_code_hashes_from_outputs.add(out['type_script']['code_hash'][:16])
        
        print("=== Script Summary ===")
        print(f"Unique lock types (from inputs): {len(lock_code_hashes_from_inputs)}")
        print(f"  {lock_code_hashes_from_inputs}")
        print(f"Unique lock types (from outputs): {len(lock_code_hashes_from_outputs)}")
        print(f"  {lock_code_hashes_from_outputs}")
        print(f"Unique type scripts (from outputs): {len(type_code_hashes_from_outputs)}")
        print(f"  {type_code_hashes_from_outputs}")
    
    collector.close()

if __name__ == "__main__":
    main()
