from __future__ import annotations

import json
import time
from dataclasses import dataclass, field


COUNTER_NAMES = (
    "explorer_requests", "explorer_successes", "explorer_failures",
    "explorer_retries", "rate_limit_events", "transaction_cache_hits",
    "transaction_cache_misses", "previous_output_cache_hits",
    "previous_output_cache_misses", "raw_cache_hits", "normalized_cache_hits",
    "block_cache_hits", "block_cache_misses", "address_page_cache_hits",
    "address_page_cache_misses", "transactions_fetched", "transactions_reused",
)


@dataclass
class CacheStats:
    counters: dict[str, int] = field(
        default_factory=lambda: {name: 0 for name in COUNTER_NAMES})

    def increment(self, name: str, amount: int = 1) -> None:
        if name not in self.counters:
            raise KeyError(f"unknown cache statistic: {name}")
        self.counters[name] += amount

    def snapshot(self) -> dict[str, int]:
        return dict(self.counters)

    def delta(self, earlier: dict[str, int]) -> dict[str, int]:
        return {name: self.counters[name] - earlier.get(name, 0)
                for name in COUNTER_NAMES}


def install_statistics_schema(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS cache_statistics (
        scope_id TEXT PRIMARY KEY,
        address TEXT,
        counters_json TEXT NOT NULL,
        updated_at INTEGER NOT NULL
    )""")


def persist_statistics(conn, scope_id: str, address: str | None,
                       counters: dict[str, int]) -> None:
    install_statistics_schema(conn)
    conn.execute(
        "INSERT OR REPLACE INTO cache_statistics VALUES (?, ?, ?, ?)",
        (scope_id, address, json.dumps(counters, sort_keys=True), int(time.time())),
    )
