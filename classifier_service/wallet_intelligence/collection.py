from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:  # Store/cache operations require only the standard library.
    requests = None
    HTTPAdapter = Retry = None

<<<<<<< HEAD:ckb_data/ckb_explorer_pull.py
from ckb_native import (
=======
from wallet_intelligence.normalization import (
>>>>>>> 3ffa0873a230edae6a181e1c5144ffb635dd7af6:classifier-service/wallet_intelligence/collection.py
    install_schema,
    normalize_transaction,
    persist_transaction,
)


BASE_URL = os.getenv("EXPLORER_API_URL", "https://mainnet-api.explorer.nervos.org/api/v1")
HEADERS = {
    "Accept": "application/vnd.api+json",
    "Content-Type": "application/vnd.api+json",
    "User-Agent": "ckb-wallet-behavior-research/1.0",
}
PAGE_SIZE = 50           
REQUEST_TIMEOUT = 30     
RATE_LIMIT_SLEEP = 0.25  
MAX_RETRIES = 5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ckb_pull")




def build_session() -> requests.Session:
    if requests is None:
        return None
    session = requests.Session()
    session.headers.update(HEADERS)
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


SESSION = build_session()


def api_get(path: str, params: Optional[dict] = None) -> Optional[dict]:
    """GET a single Explorer API endpoint, return parsed JSON or None on failure."""
    url = f"{BASE_URL}{path}"
    if SESSION is None:
<<<<<<< HEAD:ckb_data/ckb_explorer_pull.py
        from ckb_clients import ClientUnavailable, ExplorerClient
=======
        from wallet_intelligence.clients import ClientUnavailable, ExplorerClient
>>>>>>> 3ffa0873a230edae6a181e1c5144ffb635dd7af6:classifier-service/wallet_intelligence/collection.py
        try:
            return ExplorerClient(BASE_URL, timeout=REQUEST_TIMEOUT)._get(path, params)
        except ClientUnavailable as e:
            log.warning("request error %s %s: %s", url, params, e)
            return None
    try:
        resp = SESSION.get(url, params=params or {}, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        log.warning("request error %s %s: %s", url, params, e)
        return None
    time.sleep(RATE_LIMIT_SLEEP)
    if resp.status_code != 200:
        log.warning("non-200 (%s) for %s %s", resp.status_code, url, params)
        return None
    try:
        return resp.json()
    except ValueError:
        log.warning("bad JSON from %s", url)
        return None


def api_get_paginated(path: str, params: Optional[dict] = None) -> Iterator[dict]:
   
    params = dict(params or {})
    params.setdefault("page_size", PAGE_SIZE)
    page = params.get("page", 1)
    while True:
        params["page"] = page
        payload = api_get(path, params)
        if not payload:
            return
        items = payload.get("data") or []
        if not items:
            return
        for item in items:
            yield item
        total = (payload.get("meta") or {}).get("total")
        if total is not None and page * params["page_size"] >= int(total):
            return
        page += 1


SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_transactions (
    tx_hash TEXT PRIMARY KEY,
    raw_json TEXT NOT NULL,
    fetched_at INTEGER NOT NULL,
    source_kind TEXT NOT NULL DEFAULT 'ckb_explorer_api'
);

CREATE TABLE IF NOT EXISTS raw_addresses (
    address TEXT PRIMARY KEY,
    lock_hash TEXT,
    raw_json TEXT NOT NULL,
    fetched_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_address_pages (
    address TEXT NOT NULL,
    observation_window_id TEXT NOT NULL,
    page INTEGER NOT NULL,
    raw_json TEXT NOT NULL,
    fetched_at INTEGER NOT NULL,
    PRIMARY KEY (address, observation_window_id, page)
);

CREATE TABLE IF NOT EXISTS address_tx_seen (
    address TEXT NOT NULL,
    tx_hash TEXT NOT NULL,
    block_timestamp INTEGER,
    PRIMARY KEY (address, tx_hash)
);

CREATE TABLE IF NOT EXISTS edges (
    from_lock_hash TEXT NOT NULL,
    to_lock_hash TEXT NOT NULL,
    value_shannon REAL NOT NULL,
    capacity_bytes INTEGER,
    block_timestamp INTEGER,
    tx_hash TEXT NOT NULL,
    PRIMARY KEY (from_lock_hash, to_lock_hash, tx_hash)
);

CREATE TABLE IF NOT EXISTS wallets (
    lock_hash TEXT PRIMARY KEY,
    address TEXT,
    lock_code_hash TEXT,
    lock_hash_type TEXT,
    tx_count INTEGER DEFAULT 0,
    first_seen INTEGER,
    last_seen INTEGER
);

CREATE TABLE IF NOT EXISTS dao_events (
    address TEXT NOT NULL,
    event_type TEXT,
    capacity REAL,
    block_timestamp INTEGER,
    tx_hash TEXT,
    raw_json TEXT,
    UNIQUE (address, tx_hash, event_type)
);


CREATE TABLE IF NOT EXISTS queue (
    address TEXT PRIMARY KEY,
    hop INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | done
    dao_pulled INTEGER NOT NULL DEFAULT 0    -- 0/1: have we pulled DAO events for this address yet?
);

CREATE TABLE IF NOT EXISTS resolved_addresses (
    lock_hash TEXT PRIMARY KEY,
    address TEXT NOT NULL
);
"""


class Store:
    def __init__(self, db_path: Path):
        self._closed = False
        self.conn = sqlite3.connect(str(db_path))
        self.conn.executescript(SCHEMA)
        install_schema(self.conn)
        self._migrate()
        self.conn.commit()

    def _migrate(self):
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(queue)")]
        if "dao_pulled" not in cols:
            self.conn.execute(
                "ALTER TABLE queue ADD COLUMN dao_pulled INTEGER NOT NULL DEFAULT 0"
            )
        raw_cols = [r[1] for r in self.conn.execute("PRAGMA table_info(raw_transactions)")]
        if "source_kind" not in raw_cols:
            self.conn.execute(
                "ALTER TABLE raw_transactions ADD COLUMN source_kind TEXT NOT NULL "
                "DEFAULT 'ckb_explorer_api'"
            )

    def close(self):
        if self._closed:
            return
        self.conn.commit()
        self.conn.close()
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        self.close()

    def __del__(self):
        # Exception paths must not leave sqlite connections for the GC to warn on.
        try:
            self.close()
        except Exception:
            pass

    # ---- caching helpers ----

    def has_transaction(self, tx_hash: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM raw_transactions WHERE tx_hash = ?", (tx_hash,)
        )
        return cur.fetchone() is not None

    def save_transaction(self, tx_hash: str, payload: dict,
                         source_kind: str = "ckb_explorer_api"):
        collected_at = int(time.time())
        self.conn.execute(
            "INSERT OR REPLACE INTO raw_transactions "
            "(tx_hash, raw_json, fetched_at, source_kind) VALUES (?, ?, ?, ?)",
            (tx_hash, json.dumps(payload), collected_at, source_kind),
        )
        self.save_collection_receipt(
            "transaction", tx_hash, "complete",
            {"display_cells": True, "source_kind": source_kind}, collected_at=collected_at,
        )
        self.conn.commit()

    def save_address_raw(self, address: str, lock_hash: Optional[str], payload: dict):
        collected_at = int(time.time())
        self.conn.execute(
            "INSERT OR REPLACE INTO raw_addresses (address, lock_hash, raw_json, fetched_at) "
            "VALUES (?, ?, ?, ?)",
            (address, lock_hash, json.dumps(payload), collected_at),
        )
        self.save_collection_receipt("address", address, "complete", collected_at=collected_at)
        self.conn.commit()

    def save_collection_receipt(self, resource_type: str, resource_id: Optional[str],
                                status: str, request_parameters: Optional[dict] = None,
                                error: Optional[str] = None,
                                collected_at: Optional[int] = None) -> None:
        self.conn.execute(
            "INSERT INTO collection_receipts "
            "(resource_type, resource_id, source, request_parameters_json, "
            "collection_status, collected_at, error) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (resource_type, resource_id, BASE_URL,
             json.dumps(request_parameters or {}, sort_keys=True), status,
             collected_at or int(time.time()), error),
        )

    def mark_address_tx_seen(self, address: str, tx_hash: str, ts: Optional[int]):
        self.conn.execute(
            "INSERT OR IGNORE INTO address_tx_seen (address, tx_hash, block_timestamp) "
            "VALUES (?, ?, ?)",
            (address, tx_hash, ts),
        )

    def save_edge(self, from_hash: str, to_hash: str, value: float,
                  capacity_bytes: Optional[int], ts: Optional[int], tx_hash: str):
        raise RuntimeError(
            "legacy pairwise edge writes are disabled: normalized transactions/Cells "
            "are the source of truth and pairwise value attribution is NOT_ESTABLISHED"
        )

    def save_normalized_transaction(self, payload: dict,
                                    target_lock_hash: Optional[str] = None) -> dict:
        tx = normalize_transaction(payload, target_lock_hash=target_lock_hash)
        persist_transaction(self.conn, tx)
        return tx

    def upsert_wallet(self, lock_hash: str, address: Optional[str],
                       code_hash: Optional[str], hash_type: Optional[str], ts: Optional[int]):
        self.conn.execute(
            """
            INSERT INTO wallets (lock_hash, address, lock_code_hash, lock_hash_type,
                                  tx_count, first_seen, last_seen)
            VALUES (?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(lock_hash) DO UPDATE SET
                tx_count = tx_count + 1,
                first_seen = MIN(COALESCE(first_seen, ?), ?),
                last_seen = MAX(COALESCE(last_seen, ?), ?),
                address = COALESCE(wallets.address, excluded.address)
            """,
            (lock_hash, address, code_hash, hash_type, ts, ts, ts, ts, ts, ts),
        )

    def save_dao_event(self, address: str, event: dict):
        attrs = event.get("attributes", {})
        self.conn.execute(
            "INSERT OR IGNORE INTO dao_events "
            "(address, event_type, capacity, block_timestamp, tx_hash, raw_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                address,
                attrs.get("dao_event_type") or attrs.get("event_type"),
                _to_float(attrs.get("capacity")),
                _to_int(attrs.get("block_timestamp")),
                attrs.get("transaction_hash") or attrs.get("tx_hash"),
                json.dumps(event),
            ),
        )
        self.conn.commit()


    def remember_address(self, lock_hash: Optional[str], address: Optional[str]):
        if not lock_hash or not address:
            return
        self.conn.execute(
            "INSERT OR IGNORE INTO resolved_addresses (lock_hash, address) VALUES (?, ?)",
            (lock_hash, address),
        )

    def lookup_address(self, lock_hash: str) -> Optional[str]:
        cur = self.conn.execute(
            "SELECT address FROM resolved_addresses WHERE lock_hash = ?", (lock_hash,)
        )
        row = cur.fetchone()
        return row[0] if row else None

    # ---- BFS queue ----

    def enqueue(self, address: str, hop: int):
        self.conn.execute(
            "INSERT OR IGNORE INTO queue (address, hop, status) VALUES (?, ?, 'pending')",
            (address, hop),
        )

    def known(self, address: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM queue WHERE address = ?", (address,))
        return cur.fetchone() is not None

    def next_pending(self) -> Optional[tuple]:
        cur = self.conn.execute(
            "SELECT address, hop FROM queue WHERE status = 'pending' ORDER BY hop LIMIT 1"
        )
        return cur.fetchone()

    def mark_done(self, address: str):
        self.conn.execute(
            "UPDATE queue SET status = 'done' WHERE address = ?", (address,)
        )
        self.conn.commit()

    def is_dao_pulled(self, address: str) -> bool:
        cur = self.conn.execute(
            "SELECT dao_pulled FROM queue WHERE address = ?", (address,)
        )
        row = cur.fetchone()
        return bool(row and row[0])

    def mark_dao_pulled(self, address: str):
        self.conn.execute(
            "UPDATE queue SET dao_pulled = 1 WHERE address = ?", (address,)
        )
        self.conn.commit()

    def queue_size(self, status: str = "pending") -> int:
        cur = self.conn.execute("SELECT COUNT(*) FROM queue WHERE status = ?", (status,))
        return cur.fetchone()[0]

    def counts_summary(self) -> dict:
        def one(sql: str) -> int:
            return self.conn.execute(sql).fetchone()[0]
        return {
            "addresses_done": one("SELECT COUNT(*) FROM queue WHERE status='done'"),
            "addresses_pending": one("SELECT COUNT(*) FROM queue WHERE status='pending'"),
            "transactions_cached": one("SELECT COUNT(*) FROM raw_transactions"),
            "edges_cached": one("SELECT COUNT(*) FROM edges"),
            "wallets_known": one("SELECT COUNT(*) FROM wallets"),
            "dao_events_cached": one("SELECT COUNT(*) FROM dao_events"),
        }


def _to_int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _to_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None




def fetch_address_detail(address: str) -> Optional[dict]:
    payload = api_get(f"/addresses/{address}")
    return payload


def fetch_address_transactions(address: str) -> Iterator[dict]:
    yield from api_get_paginated(f"/address_transactions/{address}")


def fetch_transaction_detail(tx_hash: str) -> Optional[dict]:
    payload = api_get(f"/transactions/{tx_hash}", params={"display_cells": "true"})
    return payload


def fetch_dao_events(address: str) -> Iterator[dict]:
    yield from api_get_paginated(f"/addresses/{address}/nervos_dao_events")


def fetch_latest_block_number() -> Optional[int]:
    payload = api_get("/blocks", params={"page": 1, "page_size": 1})
    if not payload:
        return None
    items = payload.get("data") or []
    if not items:
        return None
    attrs = items[0].get("attributes", {})
    return _to_int(attrs.get("number"))


def fetch_block_hash(block_number: int) -> Optional[str]:
    payload = api_get(f"/blocks/{block_number}")
    if not payload:
        return None
    data = payload.get("data")
    if isinstance(data, list):
        data = data[0] if data else None
    if not data:
        return None
    return data.get("attributes", {}).get("block_hash")


def fetch_block_transactions(block_number: int) -> Iterator[dict]:
    block_hash = fetch_block_hash(block_number)
    if not block_hash:
        log.warning("could not resolve block hash for block %d", block_number)
        return
    yield from api_get_paginated(f"/block_transactions/{block_hash}")


def discover_seed_addresses(block_start: int, block_end: int, limit: int) -> list[str]:
    addresses: list[str] = []
    seen: set[str] = set()
    for block_num in range(block_end, block_start - 1, -1):
        if len(addresses) >= limit:
            break
        log.info("[auto-seed] scanning block %d for addresses (%d/%d found)",
                  block_num, len(addresses), limit)
        for tx_item in fetch_block_transactions(block_num):
            if len(addresses) >= limit:
                break
            attrs = tx_item.get("attributes", {})
            tx_hash = attrs.get("transaction_hash") or tx_item.get("id")
            if not tx_hash:
                continue
            detail = fetch_transaction_detail(tx_hash)
            if not detail:
                continue
            data = detail.get("data")
            if isinstance(data, list):
                data = data[0] if data else None
            if not data:
                continue
            tattrs = data.get("attributes", {})
            cells = (tattrs.get("display_inputs") or []) + (tattrs.get("display_outputs") or [])
            for cell in cells:
                addr = _extract_address(cell)
                if addr and addr not in seen:
                    seen.add(addr)
                    addresses.append(addr)
                    if len(addresses) >= limit:
                        break
    return addresses



def pull_udt_transactions(address: str) -> Iterator[dict]:
    raise NotImplementedError("Wire up /udt_transactions endpoint if token flow is in scope.")


def pull_rgb_transactions() -> Iterator[dict]:
    raise NotImplementedError("Wire up the RGB transaction list endpoint for cross-chain flow.")




def _extract_lock_hash(cell: dict) -> Optional[str]:
    lock = cell.get("lock") if isinstance(cell.get("lock"), dict) else None
    if lock:
        h = lock.get("code_hash_hash") or lock.get("hash")
        if h:
            return h
       
        code_hash = lock.get("code_hash")
        args = lock.get("args")
        if code_hash and args:
            return f"{code_hash}:{args}"
    return cell.get("address_hash") or cell.get("lock_hash") or cell.get("address")


def _extract_address(cell: dict) -> Optional[str]:

    return cell.get("address_hash") or cell.get("address")


def _extract_capacity(cell: dict) -> Optional[int]:
    cap = cell.get("capacity")
    return _to_int(cap)


def resolve_transaction_to_edges(tx_payload: dict) -> list[dict]:
    """Legacy compatibility shim; pairwise attribution is intentionally disabled."""
    return []



@dataclass
class RunConfig:
    out_dir: Path
    seed_addresses: list[str]
    hops: int
    max_addresses: int
    pull_dao: bool
    block_start: Optional[int] = None
    block_end: Optional[int] = None
    auto_blocks: int = 100
    auto_seed_count: int = 30
    max_pages_per_address: int = 100


def run(cfg: RunConfig):
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    db_path = cfg.out_dir / "ckb_explorer.sqlite"
    db_existed = db_path.exists()
    store = Store(db_path)

    seed_addresses = cfg.seed_addresses
    if not seed_addresses:
        block_end = cfg.block_end
        block_start = cfg.block_start
        if block_end is None:
            tip = fetch_latest_block_number()
            if tip is None:
                log.error("no seeds provided and could not reach Explorer to "
                          "determine the current chain tip -- aborting")
                sys.exit(1)
            block_end = tip
        if block_start is None:
            block_start = max(block_end - cfg.auto_blocks + 1, 0)

        log.info("no --seed/--seed-file given -- auto-discovering up to %d "
                  "addresses from CKB Explorer blocks %d-%d",
                  cfg.auto_seed_count, block_start, block_end)
        seed_addresses = discover_seed_addresses(block_start, block_end, cfg.auto_seed_count)
        if not seed_addresses:
            log.error("auto-discovery found no addresses in blocks %d-%d; "
                      "try --block-start/--block-end with a wider or older range",
                      block_start, block_end)
            sys.exit(1)
        log.info("auto-discovered %d seed addresses from blocks %d-%d",
                  len(seed_addresses), block_start, block_end)

    for addr in seed_addresses:
        store.enqueue(addr, hop=0)


    summary = store.counts_summary()
    if db_existed:
        log.info(
            "resuming existing database at %s: %d addresses done, %d pending, "
            "%d transactions cached, %d edges cached, %d DAO events cached",
            db_path, summary["addresses_done"], summary["addresses_pending"],
            summary["transactions_cached"], summary["edges_cached"],
            summary["dao_events_cached"],
        )
    else:
        log.info("starting fresh database at %s", db_path)

    processed = 0
    while True:
        row = store.next_pending()
        if row is None:
            break
        address, hop = row
        if processed >= cfg.max_addresses:
            log.info("hit --max-addresses limit (%d), stopping BFS "
                      "(%d addresses still pending -- rerun to continue)",
                      cfg.max_addresses, store.queue_size())
            break

        log.info("[hop %d] processing address %s (%d done, %d pending)",
                  hop, address, processed, store.queue_size())

        addr_detail = fetch_address_detail(address)
        lock_hash = None
        code_hash = hash_type = None
        if addr_detail:
            item = addr_detail.get("data")
            if isinstance(item, list):
                item = item[0] if item else None
            if item:
                attrs = item.get("attributes", {})
                lock_hash = attrs.get("lock_hash")
                lock_info = attrs.get("lock_script") or {}
                code_hash = lock_info.get("code_hash")
                hash_type = lock_info.get("hash_type")
            store.save_address_raw(address, lock_hash, addr_detail)
            store.remember_address(lock_hash, address)

        tx_count = 0
        max_tx_for_this_address = cfg.max_pages_per_address * PAGE_SIZE
        for tx_item in fetch_address_transactions(address):
            if tx_count >= max_tx_for_this_address:
                log.info(
                    "  address %s hit --max-pages-per-address (%d pages / "
                    "%d transactions) -- likely an exchange/pool/high-volume "
                    "wallet; stopping early for this address to keep the "
                    "crawl moving",
                    address, cfg.max_pages_per_address, max_tx_for_this_address,
                )
                break
            attrs = tx_item.get("attributes", {})
            tx_hash = attrs.get("transaction_hash")
            ts = _to_int(attrs.get("block_timestamp"))
            if not tx_hash:
                continue
            store.mark_address_tx_seen(address, tx_hash, ts)
            tx_count += 1

            if not store.has_transaction(tx_hash):
                detail = fetch_transaction_detail(tx_hash)
                if detail:
                    store.save_transaction(tx_hash, detail)
                else:
                    continue
            else:
                
                cur = store.conn.execute(
                    "SELECT raw_json FROM raw_transactions WHERE tx_hash = ?", (tx_hash,)
                )
                detail = json.loads(cur.fetchone()[0])

            store.save_normalized_transaction(detail, target_lock_hash=lock_hash)
            # BFS expansion from flattened value edges is disabled. Candidate
            # counterparties can be projected later from the transaction
            # hypergraph using an explicit, versioned method.

        if lock_hash:
            store.upsert_wallet(lock_hash, address, code_hash, hash_type, None)

        if cfg.pull_dao and not store.is_dao_pulled(address):
            for event in fetch_dao_events(address):
                store.save_dao_event(address, event)
            store.mark_dao_pulled(address)

        store.mark_done(address)
        store.conn.commit()
        processed += 1

    log.info("run complete: %d addresses processed this run (%d still pending overall)",
              processed, store.queue_size())
    export_csv(store, cfg.out_dir)
    store.close()


def export_csv(store: Store, out_dir: Path):
    
    edges_path = out_dir / "edges.csv"
    with open(edges_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["from_lock_hash", "to_lock_hash", "value_shannon",
                          "capacity_bytes", "block_timestamp", "tx_hash"])
        for row in store.conn.execute(
            "SELECT from_lock_hash, to_lock_hash, value_shannon, capacity_bytes, "
            "block_timestamp, tx_hash FROM edges"
        ):
            writer.writerow(row)
    log.info("wrote %s", edges_path)

    
    wallets_path = out_dir / "wallets.csv"
    with open(wallets_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["lock_hash", "address", "lock_code_hash", "lock_hash_type",
                          "tx_count", "first_seen", "last_seen"])
        for row in store.conn.execute(
            "SELECT lock_hash, address, lock_code_hash, lock_hash_type, "
            "tx_count, first_seen, last_seen FROM wallets"
        ):
            writer.writerow(row)
    log.info("wrote %s", wallets_path)

    # dao_events.csv
    dao_path = out_dir / "dao_events.csv"
    with open(dao_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["address", "event_type", "capacity", "block_timestamp", "tx_hash"])
        for row in store.conn.execute(
            "SELECT address, event_type, capacity, block_timestamp, tx_hash FROM dao_events"
        ):
            writer.writerow(row)
    log.info("wrote %s", dao_path)



def parse_args(argv: Optional[list] = None) -> RunConfig:
    p = argparse.ArgumentParser(description="Pull wallet behavior data from CKB Explorer API")
    p.add_argument("--seed-file", type=str, help="Path to a text file of seed addresses, one per line")
    p.add_argument("--seed", action="append", default=[], help="A single seed address (repeatable)")
    p.add_argument("--hops", type=int, default=0, help="BFS expansion hops beyond seed addresses (0 = seeds only)")
    p.add_argument("--max-addresses", type=int, default=200,
                    help="Cap on addresses processed THIS run (rerun the same command "
                         "to keep going -- already-done work is skipped automatically)")
    p.add_argument("--no-dao", action="store_true", help="Skip pulling Nervos DAO events")
    p.add_argument("--out-dir", type=str, default="./ckb_data",
                    help="Output directory. Reusing the same --out-dir across runs is "
                         "what makes a run resumable instead of starting from scratch.")
    p.add_argument("--block-start", type=int, default=None,
                    help="Lowest block number to scan for seed addresses when no "
                         "--seed/--seed-file is given. Defaults to (tip - --auto-blocks + 1).")
    p.add_argument("--block-end", type=int, default=None,
                    help="Highest block number to scan for seed addresses when no "
                         "--seed/--seed-file is given. Defaults to the current chain tip "
                         "(fetched live from Explorer).")
    p.add_argument("--auto-blocks", type=int, default=100,
                    help="When auto-discovering seeds (no seeds given and no --block-start), "
                         "how many of the most recent blocks to scan. Default: 100.")
    p.add_argument("--auto-seed-count", type=int, default=100,
                    help="Max number of addresses to auto-discover from blocks when no "
                         "seeds are supplied. Default: 100.")
    p.add_argument("--max-pages-per-address", type=int, default=100,
                    help="Cap on pages (at page_size=50 -> 25,000 tx max by default) "
                         "pulled for any single address before moving on. Protects "
                         "the crawl from stalling for hours on exchange/pool/whale "
                         "addresses with huge histories. Default: 100 pages.")
    args = p.parse_args(argv)

    seeds = list(args.seed)
    if args.seed_file:
        path = Path(args.seed_file)
        if not path.exists():
            log.error("seed file not found: %s", path)
            sys.exit(1)
        seeds.extend(
            line.strip() for line in path.read_text().splitlines() if line.strip()
        )


    return RunConfig(
        out_dir=Path(args.out_dir),
        seed_addresses=seeds,
        hops=args.hops,
        max_addresses=args.max_addresses,
        pull_dao=not args.no_dao,
        block_start=args.block_start,
        block_end=args.block_end,
        auto_blocks=args.auto_blocks,
        auto_seed_count=args.auto_seed_count,
        max_pages_per_address=args.max_pages_per_address,
    )


if __name__ == "__main__":
    config = parse_args()
    run(config)
