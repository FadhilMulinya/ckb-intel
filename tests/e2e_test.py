"""
tests/e2e_test.py -- end-to-end tests against the real, running services.

Unlike test_fetch_offline.py / classifier-service/test_predict_offline.py
(which mock the network and run in isolation), this suite makes real HTTP
calls against registry-service (:3000) and classifier-service (:8000) --
including a real call to the CKB mainnet Explorer/RPC APIs via
classify/ingest. It proves the two services actually work together over
HTTP, not just that each one's internal logic is correct in isolation.

REQUIRES both services already running (registry-service on :3000,
classifier-service on :8000, classifier-service started with
REGISTRY_SERVICE_URL=http://localhost:3000 so the write-back path is
exercised) -- this file does not start or stop anything itself. Use
scripts/e2e.sh to start the stack, run this suite, and tear down
automatically:

    ./scripts/e2e.sh

Or, with the stack already up via ./scripts/dev.sh in another terminal:

    python3 tests/e2e_test.py

Uses only the standard library (urllib), matching the rest of this repo's
test files -- no pytest/requests dependency.
"""
import json
import sys
import time
import urllib.error
import urllib.request

REGISTRY_BASE = "http://localhost:3000/api/v1"
CLASSIFIER_BASE = "http://localhost:8000"

# A real mainnet address with enough history to classify meaningfully --
# same one used throughout this repo's manual testing and other docs.
KNOWN_ADDRESS = "ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsq2hhwwfmxw3e2v6wya8kjw4wc7vlz9jqmgfk8t3y"

# A syntactically-plausible but never-used address, so tests that need an
# address this session has definitely never seen don't collide with
# KNOWN_ADDRESS's accumulated state across repeated test runs.
FRESH_ADDRESS = f"ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsq{int(time.time())}fresh"


def request(method, url, body=None):
    """Returns (status_code, parsed_json_or_raw_text). Never raises on HTTP
    error status codes -- callers assert on status explicitly, since 400/
    404/503 are expected, tested outcomes here, not failures of this
    helper. Non-JSON bodies (e.g. the HTML /docs pages) are returned as
    plain text rather than raising -- not every endpoint under test
    returns JSON."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read()
        status = e.code
    if not raw:
        return status, None
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw.decode("utf-8", errors="replace")


# --- tiny test runner (mirrors the PASS:/ALL CHECKS PASSED style used by
# the rest of this repo's tests, but collects failures instead of stopping
# at the first one, since a full e2e run is expensive and you want to see
# every broken endpoint in one pass, not fix-and-rerun one at a time) ----
_failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"PASS: {name}")
    else:
        msg = f"FAIL: {name}" + (f" -- {detail}" if detail else "")
        print(msg)
        _failures.append(msg)


# ============================== registry-service ==========================

def test_registry_health():
    status, body = request("GET", f"{REGISTRY_BASE}/health")
    check("GET /health -> 200 ok", status == 200 and body.get("status") == "ok", f"got {status} {body}")


def test_registry_chain_status():
    status, body = request("GET", f"{REGISTRY_BASE}/chain/status")
    check(
        "GET /chain/status -> mainnet + positive tip block",
        status == 200 and body.get("network") == "mainnet" and isinstance(body.get("tipBlockNumber"), int) and body["tipBlockNumber"] > 0,
        f"got {status} {body}",
    )

    # second call within the 5s cache window should return the identical
    # tip (proves the cache is being served, not a fresh RPC call each time)
    status2, body2 = request("GET", f"{REGISTRY_BASE}/chain/status")
    check(
        "GET /chain/status twice quickly -> same cached tip",
        status2 == 200 and body2.get("tipBlockNumber") == body.get("tipBlockNumber"),
        f"first={body}, second={body2}",
    )


def test_registry_wallets_list():
    status, body = request("GET", f"{REGISTRY_BASE}/wallets")
    check(
        "GET /wallets -> paginated shape",
        status == 200 and {"items", "total", "page", "pageSize"} <= set(body.keys()),
        f"got {status} {body}",
    )

    status, body = request("GET", f"{REGISTRY_BASE}/wallets?label=bot")
    check("GET /wallets?label=bot -> 200", status == 200, f"got {status} {body}")

    status, body = request("GET", f"{REGISTRY_BASE}/wallets?label=not-a-real-label")
    check("GET /wallets?label=<invalid> -> 400", status == 400, f"got {status} {body}")


def test_registry_wallet_not_found():
    never_seen = f"ckb1qneverseen{int(time.time() * 1000)}"
    status, body = request("GET", f"{REGISTRY_BASE}/wallets/{never_seen}")
    check("GET /wallets/<unseen address> -> 404", status == 404, f"got {status} {body}")


def test_registry_ingest():
    status, body = request("POST", f"{REGISTRY_BASE}/ingest", {"addresses": []})
    check("POST /ingest with empty addresses -> 400", status == 400, f"got {status} {body}")

    status, body = request("POST", f"{REGISTRY_BASE}/ingest", {"addresses": [KNOWN_ADDRESS]})
    ok = status == 200 and body.get("requested") == 1 and len(body.get("results", [])) == 1
    check("POST /ingest with a real mainnet address -> resolves identity", ok, f"got {status} {body}")

    status, body = request("GET", f"{REGISTRY_BASE}/wallets/{KNOWN_ADDRESS}")
    check(
        "GET /wallets/<ingested address> -> mainnet, complete",
        status == 200 and body.get("network") == "mainnet" and body.get("ingestionStatus") == "complete",
        f"got {status} {body}",
    )


def test_registry_label_write_and_autocreate():
    # PATCH on an address registry-service has never seen at all -- proves
    # the upsert/auto-create path (no ingest required first).
    status, body = request(
        "PATCH", f"{REGISTRY_BASE}/wallets/{FRESH_ADDRESS}/label", {"label": "bot", "botProbability": 0.87}
    )
    check(
        "PATCH .../label on a never-seen address -> 200, auto-created",
        status == 200 and body.get("label") == "bot" and body.get("botProbability") == 0.87,
        f"got {status} {body}",
    )

    status, body = request("PATCH", f"{REGISTRY_BASE}/wallets/{FRESH_ADDRESS}/label", {"label": "not-a-real-label"})
    check("PATCH .../label with invalid label -> 400", status == 400, f"got {status} {body}")

    status, body = request("GET", f"{REGISTRY_BASE}/wallets?label=bot")
    addrs = [w["address"] for w in body.get("items", [])] if status == 200 else []
    check("GET /wallets?label=bot -> includes the wallet just labeled", FRESH_ADDRESS in addrs, f"got items={addrs}")


def test_registry_model_evaluation():
    status, body = request("GET", f"{REGISTRY_BASE}/model/evaluation")
    if status == 503:
        check(
            "GET /model/evaluation -> 503 (classifier-service/eval_results.json not generated yet)",
            True,
        )
        return
    check(
        "GET /model/evaluation -> 200 with accuracy + lastUpdatedAt",
        status == 200 and isinstance(body.get("accuracy"), float) and isinstance(body.get("lastUpdatedAt"), str),
        f"got {status} {body}",
    )
    last_updated = body.get("lastUpdatedAt", "") if status == 200 else ""
    # ISO-8601 looks like "2026-08-01T20:41:24.608Z" -- a literal "T"
    # between date and time digits. Human-readable ("Aug 1, 2026, 8:41 PM
    # UTC") never has that shape, even though "UTC" itself contains a T,
    # so check for the digit-T-digit pattern specifically, not just "T".
    import re
    looks_like_iso = bool(re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", last_updated))
    check(
        "GET /model/evaluation -> lastUpdatedAt is human-readable, not ISO-8601",
        status != 200 or (not looks_like_iso and "UTC" in last_updated),
        f"got lastUpdatedAt={last_updated}",
    )


def test_registry_docs():
    status, body = request("GET", f"{REGISTRY_BASE}/docs")
    check("GET /api/v1/docs -> 200 html", status == 200, f"got {status}")

    status, body = request("GET", f"{REGISTRY_BASE}/openapi.json")
    paths = set(body.get("paths", {}).keys()) if status == 200 and isinstance(body, dict) else set()
    expected = {"/health", "/chain/status", "/wallets", "/wallets/{address}", "/wallets/{address}/label", "/ingest", "/model/evaluation"}
    check(
        "GET /api/v1/openapi.json -> documents all 7 endpoints",
        status == 200 and expected <= paths,
        f"got {status}, paths={paths}",
    )


# ============================== classifier-service =========================

def test_classifier_health():
    status, body = request("GET", f"{CLASSIFIER_BASE}/health")
    check("GET /health -> 200 or 503 with a status field", status in (200, 503) and "status" in (body or {}), f"got {status} {body}")


def test_classifier_root():
    status, body = request("GET", f"{CLASSIFIER_BASE}/")
    check("GET / -> points at docs", status == 200 and body.get("docs") == "/api/v1/docs", f"got {status} {body}")


def test_classifier_classify_valid():
    status, body = request("GET", f"{CLASSIFIER_BASE}/classify/{KNOWN_ADDRESS}")
    ok = status == 200 and body.get("verdict") in ("bot", "human", "uncertain", "unknown") and body.get("address") == KNOWN_ADDRESS
    check("GET /classify/<real address> -> valid verdict", ok, f"got {status} {body}")
    return body


def test_classifier_classify_max_tx_bounds():
    status, body = request("GET", f"{CLASSIFIER_BASE}/classify/{KNOWN_ADDRESS}?max_tx=1")
    check("GET /classify?max_tx=1 (below min) -> 400", status == 400, f"got {status} {body}")

    status, body = request("GET", f"{CLASSIFIER_BASE}/classify/{KNOWN_ADDRESS}?max_tx=5000")
    check("GET /classify?max_tx=5000 (above max) -> 400", status == 400, f"got {status} {body}")


def test_classifier_docs():
    status, body = request("GET", f"{CLASSIFIER_BASE}/api/v1/docs")
    check("GET /api/v1/docs -> 200 html", status == 200, f"got {status}")

    status, body = request("GET", f"{CLASSIFIER_BASE}/api/v1/openapi.json")
    paths = set(body.get("paths", {}).keys()) if status == 200 and isinstance(body, dict) else set()
    check(
        "GET /api/v1/openapi.json -> documents /classify/{address}",
        status == 200 and "/classify/{address}" in paths,
        f"got {status}, paths={paths}",
    )


# ============================== cross-service integration ==================

def test_cross_service_classify_writes_back_to_registry():
    """The actual point of this repo's two-service architecture: classify
    on Python, then confirm the result shows up on Node without anything
    else being called in between. Requires classifier-service to have been
    started with REGISTRY_SERVICE_URL set (scripts/e2e.sh does this)."""
    status, classify_body = request("GET", f"{CLASSIFIER_BASE}/classify/{KNOWN_ADDRESS}")
    if status != 200 or classify_body.get("verdict") == "unknown":
        check("cross-service write-back", False, f"classify didn't produce a usable verdict: {status} {classify_body}")
        return

    # write-back happens synchronously inside the classify() call, so no
    # polling/sleep needed -- it's already done by the time this responds.
    status, wallet = request("GET", f"{REGISTRY_BASE}/wallets/{KNOWN_ADDRESS}")
    check(
        "classify() verdict matches registry-service's stored label",
        status == 200 and wallet.get("label") == classify_body.get("verdict"),
        f"classify said {classify_body.get('verdict')}, registry has {wallet.get('label') if status == 200 else (status, wallet)}",
    )
    check(
        "classify() bot_probability matches registry-service's stored botProbability",
        status == 200 and wallet.get("botProbability") == classify_body.get("bot_probability"),
        f"classify said {classify_body.get('bot_probability')}, registry has {wallet.get('botProbability') if status == 200 else 'N/A'}",
    )


def run():
    tests = [
        test_registry_health,
        test_registry_chain_status,
        test_registry_wallets_list,
        test_registry_wallet_not_found,
        test_registry_ingest,
        test_registry_label_write_and_autocreate,
        test_registry_model_evaluation,
        test_registry_docs,
        test_classifier_health,
        test_classifier_root,
        test_classifier_classify_valid,
        test_classifier_classify_max_tx_bounds,
        test_classifier_docs,
        test_cross_service_classify_writes_back_to_registry,
    ]
    for t in tests:
        try:
            t()
        except Exception as e:  # noqa: BLE001 -- a crashed test is still a failure to report, not a reason to abort the run
            msg = f"FAIL: {t.__name__} raised {type(e).__name__}: {e}"
            print(msg)
            _failures.append(msg)

    print()
    if _failures:
        print(f"{len(_failures)} FAILURE(S):")
        for f in _failures:
            print(" -", f)
        sys.exit(1)
    print("ALL END-TO-END CHECKS PASSED")


if __name__ == "__main__":
    run()
