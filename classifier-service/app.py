"""
app.py -- FastAPI/uvicorn wrapper around predict.classify() for deploying
the bot/human classifier as an HTTP service.

Deliberately thin: all real logic (fetch, features, model, uncertain band)
stays in predict.py, which is also usable standalone from the CLI. This
file only adds an HTTP layer + input validation + a health check, so
predict.py doesn't quietly develop two divergent code paths.

RUN LOCALLY
-----------
    pip install -r requirements.txt fastapi uvicorn
    uvicorn app:app --host 0.0.0.0 --port 8000 --reload
    # (MODEL_PATH resolves relative to this file's location, not cwd, so
    # this works whether you run it from classifier-service/ or its parent dir)

    # from another terminal:
    curl "http://localhost:8000/classify/ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsq9j8mmc2fzdz24pkq4rrfe3nkywsflvtn2v9wc9"
    curl http://localhost:8000/health

Full interactive API reference: http://localhost:8000/api/v1/docs

DEPLOYMENT
----------
See the accompanying Dockerfile in this directory for a container-based
deploy -- build context is classifier-service/ so it can COPY both
requirements.txt and the rest of this directory in one shot.
"""
from fastapi import FastAPI, HTTPException, Path, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import Optional

import predict as pr

EXAMPLE_ADDRESS = "ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsq2hhwwfmxw3e2v6wya8kjw4wc7vlz9jqmgfk8t3y"

app = FastAPI(
    title="CKB Bot/Human Classifier",
    description=(
        "Classifies a CKB mainnet address as bot-operated or human-operated from its real "
        "transaction history. Fetches the address's history from the CKB Explorer mainnet API, "
        "extracts 10 behavioral features (timing regularity, amount variation, counterparty "
        "fan-out -- never raw magnitudes), and scores it with a trained Random Forest classifier. "
        "This service does the entire classification job itself -- it does not depend on, or "
        "require, the separate registry-service (Node) wallet registry to function. See "
        "classifier-service/README.md for methodology, feature definitions, and evaluation results, "
        "and label-provenance caveats before trusting any single verdict as ground truth."
    ),
    version="1.0",
    # Spec + default Swagger/ReDoc UIs moved under /api/v1 -- /api/v1/docs is
    # Scalar instead (see below), served against the auto-generated
    # /api/v1/openapi.json FastAPI already produces. No schema authoring
    # needed here, unlike registry-service's hand-written openapi.ts -- FastAPI
    # derives it from the route signatures/response_model/Field(...)
    # descriptions below. The actual endpoints (/health, /classify/{address})
    # stay unversioned as they already were; only the docs surface moved to
    # match registry-service's shape.
    openapi_url="/api/v1/openapi.json",
    docs_url=None,
    redoc_url=None,
)

# Load once at process start, not per-request -- joblib.load() + the sklearn
# bundle is not free, and predict.classify() currently reloads it internally.
# We keep using classify()'s own loading for correctness (single source of
# truth), but warm it once here so the first real request isn't slow AND so
# a broken/missing model.joblib fails fast at startup, not on first request.
_startup_ok = {"loaded": False, "error": None}


@app.on_event("startup")
def _warm_model():
    try:
        import joblib
        joblib.load(pr.MODEL_PATH)
        _startup_ok["loaded"] = True
    except Exception as e:  # noqa: BLE001 -- deliberately broad, this is a health signal
        _startup_ok["error"] = str(e)


class ClassifyResponse(BaseModel):
    address: str = Field(description="The address that was classified.", example=EXAMPLE_ADDRESS)
    n_tx_fetched: int = Field(
        description="How many transactions were actually fetched from the Explorer API for this address (capped by max_tx).",
        example=30,
    )
    bot_probability: Optional[float] = Field(
        None,
        description="The model's raw bot-probability score, 0-1. Null only when verdict is \"unknown\" (too little history to score at all).",
        example=0.9593,
    )
    verdict: str = Field(
        description=(
            "One of exactly four values -- this is the field registry-service's wallet registry mirrors byte-for-byte when "
            "REGISTRY_SERVICE_URL is set:\n"
            "- `bot` -- classified as automated/bot-operated behavior.\n"
            "- `human` -- classified as human-operated behavior.\n"
            "- `uncertain` -- bot_probability fell inside the model's calibrated uncertain band; not a confident call, route to manual review.\n"
            "- `unknown` -- fewer than 2 transactions were found; not enough history to extract behavioral features at all."
        ),
        example="bot",
    )
    warning: Optional[str] = Field(
        None,
        description="Present when verdict is \"uncertain\", or when history is short enough that interval-based features are degenerate by construction. Explains why this specific verdict should be treated as low-confidence.",
    )
    reason: Optional[str] = Field(
        None,
        description="Present only when verdict is \"unknown\" -- explains why (e.g. \"only 1 transaction(s) found\").",
    )


class HealthResponse(BaseModel):
    status: str = Field(description="\"ok\" if the trained model loaded successfully at startup, \"degraded\" otherwise.", example="ok")
    model_path: str = Field(description="Absolute filesystem path to the model.joblib bundle this instance loaded.")
    error: Optional[str] = Field(None, description="Present only when status is \"degraded\" -- the exception raised while loading the model.")


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Liveness + model-load check",
    description=(
        "Reports whether the trained model (model.joblib) loaded successfully when this process started. "
        "The model is loaded once at startup (not per-request) specifically so a broken or missing model.joblib "
        "fails fast here, visibly, rather than on someone's first live classification request. "
        "Returns HTTP 503 (not 200) when degraded, so this doubles as a container/load-balancer health probe."
    ),
    responses={
        200: {"description": "Model loaded successfully; service is fully functional."},
        503: {"description": "Model failed to load at startup -- /classify will fail with 500 until this is fixed and the process restarts."},
    },
)
def health():
    status = "ok" if _startup_ok["loaded"] else "degraded"
    body = {"status": status, "model_path": pr.MODEL_PATH}
    if _startup_ok["error"]:
        body["error"] = _startup_ok["error"]
    return JSONResponse(body, status_code=200 if _startup_ok["loaded"] else 503)


@app.get(
    "/classify/{address}",
    response_model=ClassifyResponse,
    tags=["Classification"],
    summary="Classify a CKB address as bot or human",
    description=(
        "Fetches the address's transaction history from the CKB Explorer mainnet API, extracts behavioral "
        "features, and scores it with the trained classifier. Mirrors `python3 predict.py <address> --json` "
        "exactly -- same function, same model, same uncertain-band logic, nothing added or skipped for the "
        "HTTP path.\n\n"
        "If `REGISTRY_SERVICE_URL` is set in this process's environment, the resulting verdict is also written back "
        "to the registry-service wallet registry as a side effect (best-effort -- a failure there never affects this "
        "response). That is entirely optional; this endpoint fetches and classifies on its own regardless."
    ),
    responses={
        200: {"description": "Classification succeeded (verdict may still be \"unknown\" if history was too short)."},
        400: {"description": "max_tx was outside the allowed 2-1000 range."},
        502: {"description": "The upstream CKB Explorer API failed (rate limited, address not found, timeout, etc.) -- not this service's fault."},
        500: {"description": "This deployment is misconfigured -- model.joblib is missing or corrupt. Check GET /health."},
    },
)
def classify_address(
    address: str = Path(description="A CKB mainnet address to classify.", example=EXAMPLE_ADDRESS),
    max_tx: int = Query(
        300,
        description="Maximum recent transactions to fetch and use for feature extraction (2-1000). Most-recent-first, so this caps history depth, not just page count. Out-of-range values return 400 with a clear message, not FastAPI's generic 422 -- validated manually below on purpose.",
    ),
):
    if max_tx < 2 or max_tx > 1000:
        raise HTTPException(status_code=400, detail="max_tx must be between 2 and 1000")
    try:
        result = pr.classify(address, max_tx=max_tx)
    except pr.ApiError as e:
        # upstream explorer API issue (rate limit, address not found, timeout)
        # -- surface as 502, not 500, since it's not our code that's broken
        raise HTTPException(status_code=502, detail=str(e))
    except pr.ModelLoadError as e:
        # our deployment is misconfigured (missing/corrupt model.joblib) --
        # surface as 500, distinct from an upstream API problem
        raise HTTPException(status_code=500, detail=str(e))
    return result


@app.get("/api/v1/docs", response_class=HTMLResponse, include_in_schema=False)
def scalar_docs():
    return """<!doctype html>
<html>
  <head>
    <title>CKB Bot/Human Classifier -- API docs</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
  </head>
  <body>
    <script id="api-reference" data-url="/api/v1/openapi.json"></script>
    <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
  </body>
</html>"""


@app.get(
    "/",
    tags=["Health"],
    summary="Service pointer",
    description="Minimal landing response -- points to the full API docs. Not meant to carry any real information itself.",
)
def root():
    return {
        "service": "ckb-bot-oneclass",
        "docs": "/api/v1/docs",
    }
