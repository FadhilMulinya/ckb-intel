"""All service environment variables and defaults in one place.

Properties preserve runtime lookup for CLI/research callers and newly created
Explorer clients. Compose supplies production overrides via the root .env file;
this module does not read or modify the frozen dataset.
"""
from __future__ import annotations

import os

DEFAULT_EXPLORER_API_URL = "https://mainnet-api.explorer.nervos.org/api/v1"


class Environments:
    @property
    def explorer_api_url(self) -> str:
        return os.getenv("EXPLORER_API_URL", DEFAULT_EXPLORER_API_URL)

    @property
    def explorer_timeout_seconds(self) -> float:
        return float(os.getenv("EXPLORER_TIMEOUT_SECONDS", "20"))

    @property
    def explorer_max_retries(self) -> int:
        return int(os.getenv("EXPLORER_MAX_RETRIES", "3"))

    @property
    def explorer_request_delay_ms(self) -> int:
        return int(os.getenv("EXPLORER_REQUEST_DELAY_MS", "250"))

    @property
    def explorer_live_page_size(self) -> int:
        return max(1, int(os.getenv("EXPLORER_LIVE_PAGE_SIZE", "50")))

    @property
    def max_concurrent_analyses(self) -> int:
        value = int(os.getenv("MAX_CONCURRENT_ANALYSES", "2"))
        if value < 1:
            raise ValueError("MAX_CONCURRENT_ANALYSES must be positive")
        return value

    # Existing research/CLI clients only; live V2 uses Explorer, not a local node.
    @property
    def ckb_rpc_url(self) -> str:
        return os.getenv("CKB_RPC_URL", "http://127.0.0.1:8114")

    @property
    def ckb_indexer_url(self) -> str:
        return os.getenv("CKB_INDEXER_URL", self.ckb_rpc_url)


environments = Environments()
