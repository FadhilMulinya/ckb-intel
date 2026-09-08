import os


EXPLORER_BASE_URL = os.environ.get("CKB_EXPLORER_BASE_URL", "https://mainnet-api.explorer.nervos.org")
EXPLORER_API_PREFIX = "/api/v1"
EXPLORER_API_V2_PREFIX = "/api/v2"
EXPLORER_HEADERS = {
    "Accept": "application/vnd.api+json",
    "Content-Type": "application/vnd.api+json",
    "User-Agent": "ckb-wallet-intel-research/1.0",
}

REQUEST_TIMEOUT_S = 25
MAX_RETRIES = 5           
BACKOFF_BASE_S = 1.5
MIN_REQUEST_INTERVAL_S = 0.35  


PAGE_MAX_RETRIES = 2
PAGE_BACKOFF_BASE_S = 1.5


CHECKPOINT_EVERY_N_PAGES = 2


MAX_SECONDS_PER_WALLET = 90


MAX_PAGES_PER_WALLET = 400



OBSERVATION_WINDOW_DAYS = 30

MAX_TX_PER_WALLET = 4000
PAGE_SIZE = 50


MIN_TX_FOR_EVIDENCE = 5
MIN_TX_FOR_PERIODICITY = 8


ACTIVITY_BUCKETS = [
    (1, 10), (11, 50), (51, 200), (201, 500), (501, 1000), (1001, 5000), (5001, 10 ** 9)
]
TARGET_WALLETS_PER_BUCKET = 40  


KNOWN_LOCK_FAMILIES = {
    "0x9bd7e06f3ecf4be0f2fcd2188b23f1b9fcc88e5d4b65a8637b17723bbda3cce8": "SECP256K1_BLAKE160",
    "0x5c5069eb0857efc65e1bca0c07df34c31663b3622fd3876c876320fc9634e2a": "SECP256K1_MULTISIG",
    "0x9f3aeaf2fc439549cbc870c653374943af96a0658bc6088966fc90fbb0bf336": "ANYONE_CAN_PAY",
    "0x60d5f39efce409c587cb9ea359cefdead650ca128f0bd9dd542df5b41f19502": "OMNILOCK",
    "0xf1951123466e4479842387a66fabfd6b04c42a3aa9c6b13c2b477c3d0c6c81ff": "CHEQUE",
}

DAO_TYPE_CODE_HASH = "0x82d76d1b75fe2fd9a27dfbaa65a039221a380d76c926f378d3f81cf3e7e13f2"

SUDT_TYPE_CODE_HASH = "0x5e7a36a77e68eecc013dfa2fe6a23f3b6c344b04005808694ae6dd45eea4103"

RAW_DIR = os.path.join(os.path.dirname(__file__), "data", "raw")
PROCESSED_DIR = os.path.join(os.path.dirname(__file__), "data", "processed")
MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")

for _d in (RAW_DIR, PROCESSED_DIR, MODELS_DIR):
    os.makedirs(_d, exist_ok=True)


SAMPLE_MANIFEST_PATH = os.path.join(PROCESSED_DIR, "sample_manifest.json")


LEAKAGE_GUARD_COLUMNS = [
    "transactions_observed", "pull_status", "hit_max_cap", "evidence_state",
    "periodicity_evidence", "window_days", "address", "label", "label_confidence",
    "reason_codes",
]
