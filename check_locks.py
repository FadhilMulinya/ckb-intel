#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('ckb_data/ckb-behaviour-dataset-v1.sqlite')
cursor = conn.cursor()

# First, get observation_id for our test wallet
addr = 'ckb1qrgqep8saj8agswr30pls73hra28ry8jlnlc3ejzh3dl2ju7xxpjxqgqqyjw0y2p7ahcysl4qhq97x60svqn29492qpkvy2s'
cursor.execute("SELECT observation_id FROM wallet_observations WHERE address = ? LIMIT 1", (addr,))
obs_id = cursor.fetchone()
if not obs_id:
    print("No wallet found")
    exit()

obs_id = obs_id[0]
print(f"observation_id: {obs_id}\n")

# Now check the locks in their outputs
cursor.execute("""
SELECT lock_script_hash, lock_identifier, type_script_hash, COUNT(*) as count
FROM cells c
WHERE c.creating_tx_hash IN (
  SELECT t.tx_hash FROM transactions t
  JOIN wallet_transaction_participation wtp ON t.tx_hash = wtp.tx_hash
  WHERE wtp.observation_id = ?
)
GROUP BY lock_script_hash, lock_identifier, type_script_hash
""", (obs_id,))

print('Results:')
rows = cursor.fetchall()
for row in rows:
    lock_hash = row[0] if row[0] else "NULL"
    lock_id = row[1][:50] if row[1] else "NULL"
    type_hash = row[2] if row[2] else "NULL"
    count = row[3]
    print(f"  lock_hash={lock_hash[:20]}... | lock_id={lock_id}... | type_hash={type_hash[:20]}... | count={count}")

print(f"\nTotal output rows: {sum(row[3] for row in rows)}")
