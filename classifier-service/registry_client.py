"""
registry_client.py -- thin write-back client for the registry-service
(Node) wallet registry.

Scope is deliberately tiny: registry-service does not store transaction
data (see ../registry-service/README.md), so predict.py keeps fetching
transaction history directly from the Explorer API exactly as it always
has -- nothing about that path changes. The only thing this module does is
write a classification result back to registry-service after predict.py
scores a wallet, so it's queryable via its REST API (GET /wallets?label=bot,
etc).

`label` values sent here are exactly predict.py's own `verdict` values
(bot/human/uncertain/unknown) -- no translation layer, because
registry-service's Wallet.label enum was defined to match this module's
caller, not the other way around.

No separate "create the wallet first" call is needed: PATCH .../label
upserts on the Node side, so it works even for an address registry-service
has never ingested (see its wallet.repository.ts updateLabel).

USAGE
-----
Only used when REGISTRY_SERVICE_URL is set (see predict.py); with it
unset, nothing in this file is imported or called, so the direct-Explorer
path is completely unaffected.
"""
import json
import urllib.request

TIMEOUT_S = 10


def write_back_label(address, base_url, label, bot_probability=None):
    """PATCH /api/v1/wallets/:address/label."""
    body = {"label": label}
    if bot_probability is not None:
        body["botProbability"] = bot_probability

    url = base_url.rstrip("/") + f"/api/v1/wallets/{address}/label"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="PATCH")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))
