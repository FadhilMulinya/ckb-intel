import time
import logging
import requests

import config

logger = logging.getLogger("ckb_wallet_intel.explorer_client")

_last_request_ts = [0.0]


def _throttle():
    elapsed = time.time() - _last_request_ts[0]
    wait = config.MIN_REQUEST_INTERVAL_S - elapsed
    if wait > 0:
        time.sleep(wait)
    _last_request_ts[0] = time.time()


def _get(path, params=None, api_version="v1", max_retries=None, backoff_base=None):
    prefix = config.EXPLORER_API_PREFIX if api_version == "v1" else config.EXPLORER_API_V2_PREFIX
    url = f"{config.EXPLORER_BASE_URL}{prefix}{path}"
    max_retries = config.MAX_RETRIES if max_retries is None else max_retries
    backoff_base = config.BACKOFF_BASE_S if backoff_base is None else backoff_base
    last_exc = None
    for attempt in range(1, max_retries + 1):
        _throttle()
        try:
            resp = requests.get(
                url, params=params, headers=config.EXPLORER_HEADERS,
                timeout=config.REQUEST_TIMEOUT_S,
            )
            if resp.status_code == 429:
                sleep_s = backoff_base * (2 ** attempt)
                logger.warning("429 rate-limited on %s, backing off %.1fs", url, sleep_s)
                time.sleep(sleep_s)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < max_retries:
                sleep_s = backoff_base * (2 ** (attempt - 1))
                logger.warning("Request failed (%s) attempt %d/%d, retrying in %.1fs: %s",
                                url, attempt, max_retries, sleep_s, exc)
                time.sleep(sleep_s)
    raise RuntimeError(f"GET {url} failed after {max_retries} attempts: {last_exc}")


def _unwrap(payload):
    """Normalize the {"data": {"attributes": {...}}} JSON:API envelope."""
    data = payload.get("data")
    if data is None:
        return None, payload.get("meta")
    if isinstance(data, list):
        items = [d.get("attributes", d) for d in data]
        return items, payload.get("meta")
    return data.get("attributes", data), payload.get("meta")


def get_tip_block_number() -> int:
    payload = _get("/statistics")
    attrs, _ = _unwrap(payload)
    return int(attrs.get("tip_block_number", 0))


def get_block(number_or_hash):
    payload = _get(f"/blocks/{number_or_hash}")
    attrs, _ = _unwrap(payload)
    return attrs


def get_recent_block_range(n_blocks: int, end_block: int = None):
    """Return block attribute dicts for the last n_blocks up to end_block (inclusive)."""
    if end_block is None:
        end_block = get_tip_block_number()
    blocks = []
    for num in range(end_block, max(end_block - n_blocks, 0), -1):
        try:
            blocks.append(get_block(num))
        except RuntimeError as exc:
            logger.warning("Skipping block %s: %s", num, exc)
    return blocks


def get_address_info(address: str):
    payload = _get(f"/addresses/{address}")
    attrs, _ = _unwrap(payload)
    return attrs


def get_address_transactions_page(address: str, page: int, page_size: int = None):
    """Fetch exactly one page. Uses the short PAGE_MAX_RETRIES budget (not the
    long general-purpose MAX_RETRIES) so a flaky page fails fast and lets the
    caller checkpoint + move on instead of blocking for minutes on one wallet.
    Returns (items: list[dict], total: int)."""
    page_size = page_size or config.PAGE_SIZE
    payload = _get(
        f"/address_transactions/{address}",
        params={"page": page, "page_size": page_size, "sort": "time.desc"},
        max_retries=config.PAGE_MAX_RETRIES, backoff_base=config.PAGE_BACKOFF_BASE_S,
    )
    items, meta = _unwrap(payload)
    return items or [], (meta or {}).get("total", 0)


def get_transaction(tx_hash: str):
    payload = _get(f"/transactions/{tx_hash}")
    attrs, _ = _unwrap(payload)
    return attrs
