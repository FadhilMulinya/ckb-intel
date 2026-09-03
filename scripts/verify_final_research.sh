#!/usr/bin/env bash
set -euo pipefail
PYTHON_BIN="${1:-python3}"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
export PYTHONPATH="$ROOT_DIR/ckb_data"
"$PYTHON_BIN" - <<'PY'
import csv, hashlib, json, sqlite3
from pathlib import Path
r=Path('ckb_data'); db=r/'ckb_data_v2/ckb_explorer.sqlite'
c=json.loads((r/'feature_engineering_v2/dataset_v1_snapshot/dataset_contract_v1.json').read_text())
assert c['total_wallets']==1172 and c['transaction_count']==51816
assert c['manifest_hash']=='6d8b5cd777e9ea9825466dc7500fdcb1dd639981d74475387c405aa6599583fe'
assert hashlib.sha256(db.read_bytes()).hexdigest()=='e74b12f269c5b5bbc9acb4d39d11e9259769b01299ec0c310d91fd38d43ff322'
conn=sqlite3.connect(f'file:{db.resolve()}?mode=ro',uri=True);assert conn.execute('pragma quick_check').fetchone()[0]=='ok';conn.close()
files=['dataset_completion/population_manifest_v1.jsonl','feature_engineering_v2/wallet_behaviour_features_v2.csv','feature_engineering_v2/wallet_behaviour_features_v2_ml.csv','feature_engineering_v2/wallet_behaviour_features_v2_metadata.csv','feature_engineering_v2/wallet_behaviour_features_v2_evidence.jsonl']
for name in files:
 p=r/name
 with p.open() as f: count=sum(1 for _ in f)-(1 if p.suffix=='.csv' else 0)
 assert count==1172,(name,count)
phase2=json.loads((r/'exploratory_ml_phase2_v1/experiment_contract.json').read_text());assert phase2['source_integrity']==json.loads((r/'exploratory_ml_phase2_v1/source_integrity_after.json').read_text())
print('Frozen contracts, hashes, 1,172-row alignment, and SQLite integrity: OK')
PY
"$PYTHON_BIN" -m unittest discover -s ckb_data -p 'test_*.py'
echo "FINAL_RESEARCH_OFFLINE_VERIFICATION_OK"
