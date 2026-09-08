"""
Verifies the exact behaviour the user hit in production: a wallet pull that
fails partway through (network timeout) must NOT lose progress, and a later
call with the same arguments must resume from the last checkpoint rather than
re-fetching from page 1.

No real network calls: explorer_client.get_address_transactions_page is
monkeypatched to serve a fake, paginated, in-memory transaction set and to
fail on demand for specific pages.
"""

import os
import sys
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import acquisition
import explorer_client as ec

import time

ADDRESS = "0xRESUME_TEST"
PAGE_SIZE = config.PAGE_SIZE
TOTAL_TX = 260  # -> ceil(260/50) = 6 pages
NOW_MS = int(time.time() * 1000)  # must be "now" - pull_wallet_raw windows against real wall-clock time


def make_fake_pages():
    """All transactions are well inside the 30-day window and newest-first."""
    all_tx = []
    for i in range(TOTAL_TX):
        all_tx.append({
            "transaction_hash": f"0xtx{i}",
            "block_number": str(9000 - i),
            "block_timestamp": str(NOW_MS - i * 3600_000),
            "is_cellbase": False,
            "display_inputs": [{"address_hash": ADDRESS, "capacity": str(10_000_000_00), "cell_index": "0",
                                 "from_cellbase": False, "since": 0, "generated_tx_hash": None, "cell_type": "normal"}],
            "display_outputs": [{"address_hash": "0xcounterparty", "capacity": str(9_900_000_00), "cell_index": "0",
                                  "cell_type": "normal"}],
        })

    pages = []
    for start in range(0, TOTAL_TX, PAGE_SIZE):
        pages.append(all_tx[start:start + PAGE_SIZE])
    return pages


PAGES = make_fake_pages()


def clean_cache():
    path = acquisition._cache_path(ADDRESS)
    if os.path.exists(path):
        os.remove(path)


def main():
    clean_cache()
    ec.get_address_info = lambda addr: {"lock_hash": "0xfakelock", "address_hash": addr}

    # --- Attempt 1: succeed on pages 1-2, then fail (simulated timeout) on page 3 ---
    call_count = {"n": 0}
    FAIL_AT_PAGE = 3

    def flaky_page_fetch(address, page, page_size=None):
        call_count["n"] += 1
        if page == FAIL_AT_PAGE:
            raise RuntimeError("simulated read timeout")
        idx = page - 1
        items = PAGES[idx] if idx < len(PAGES) else []
        return items, TOTAL_TX

    ec.get_address_transactions_page = flaky_page_fetch
    record1 = acquisition.pull_wallet_raw(ADDRESS, window_days=30)

    assert record1["status"] == "partial", f"expected partial after simulated failure, got {record1['status']}"
    assert record1["next_page"] == FAIL_AT_PAGE, f"expected to be stuck at page {FAIL_AT_PAGE}, got {record1['next_page']}"
    collected_after_attempt1 = len(record1["transactions"])
    expected_after_attempt1 = (FAIL_AT_PAGE - 1) * PAGE_SIZE
    assert collected_after_attempt1 == expected_after_attempt1, (
        f"expected {expected_after_attempt1} tx collected before the failure, got {collected_after_attempt1}"
    )
    calls_in_attempt1 = call_count["n"]
    print(f"Attempt 1: status={record1['status']}, next_page={record1['next_page']}, "
          f"tx_collected={collected_after_attempt1}, api_calls_made={calls_in_attempt1}")

    # --- Attempt 2: network recovers fully; resume the SAME wallet ---
    call_count["n"] = 0

    def healthy_page_fetch(address, page, page_size=None):
        call_count["n"] += 1
        idx = page - 1
        items = PAGES[idx] if idx < len(PAGES) else []
        return items, TOTAL_TX

    ec.get_address_transactions_page = healthy_page_fetch
    record2 = acquisition.pull_wallet_raw(ADDRESS, window_days=30)

    assert record2["status"] == "complete", f"expected complete on resume, got {record2['status']}"
    assert len(record2["transactions"]) == TOTAL_TX, (
        f"expected all {TOTAL_TX} tx after resume, got {len(record2['transactions'])}"
    )
    calls_in_attempt2 = call_count["n"]
    expected_remaining_pages = len(PAGES) - (FAIL_AT_PAGE - 1)
    print(f"Attempt 2 (resume): status={record2['status']}, tx_total={len(record2['transactions'])}, "
          f"api_calls_made={calls_in_attempt2} (expected ~{expected_remaining_pages})")

    assert calls_in_attempt2 <= expected_remaining_pages, (
        "Resume re-fetched pages that were already collected before the failure - "
        f"made {calls_in_attempt2} calls but only {expected_remaining_pages} remaining pages existed."
    )

    # --- Attempt 3: calling again on an already-complete wallet should hit ZERO API calls ---
    call_count["n"] = 0

    def should_not_be_called(address, page, page_size=None):
        call_count["n"] += 1
        raise AssertionError("pull_wallet_raw should not call the API again for a completed wallet")

    ec.get_address_transactions_page = should_not_be_called
    record3 = acquisition.pull_wallet_raw(ADDRESS, window_days=30)
    assert record3["status"] == "complete"
    assert call_count["n"] == 0, "Completed wallet triggered unnecessary API calls on re-run"
    print(f"Attempt 3 (already complete): api_calls_made={call_count['n']} (expected 0)")

    clean_cache()
    print("\nRESUMABILITY TEST PASSED: no lost progress, no wasted re-fetching, no re-work on completed wallets.")


if __name__ == "__main__":
    main()
