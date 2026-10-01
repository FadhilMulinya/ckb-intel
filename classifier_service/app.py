from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from threading import BoundedSemaphore

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from environments import environments
from v2_service import AnalysisError, V2WalletService

app = FastAPI(
    title="CKB Wallet Behaviour Intelligence Service",
    version="2.0.0",
    description=(
        "Observable CKB-native wallet behaviour features and descriptive rules. "
        "This service does not classify human/bot identity or ownership."
    ),
)
service = V2WalletService()
live_slots = BoundedSemaphore(environments.max_concurrent_analyses)


class WalletAnalysisRequest(BaseModel):
    address: str = Field(..., min_length=1, max_length=2048, description="Mainnet CKB bech32 address")
    mode: str = Field("frozen", pattern="^(frozen|live)$")


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "healthy", "service": "wallet-behaviour-v2",
            "timestamp": datetime.now(timezone.utc).isoformat()}


@app.post("/analyze")
def analyze(request: WalletAnalysisRequest) -> dict[str, Any]:
    live = request.mode == "live"
    if live and not live_slots.acquire(blocking=False):
        raise HTTPException(status_code=503, headers={"Retry-After": "5"},
                            detail={"status": "ANALYSIS_BUSY", "message": "Live analysis capacity is busy; retry later"})
    try:
        return service.analyze(request.address, live=live)
    except AnalysisError as exc:
        raise HTTPException(status_code=400 if exc.status == "INVALID_ADDRESS" else 422,
                            detail={"status": exc.status, "message": str(exc)}) from exc
    finally:
        # Hold the slot until work actually ends, even if the caller times out.
        if live:
            live_slots.release()


@app.get("/docs-overview")
def docs_overview() -> dict[str, Any]:
    return {
        "service": "CKB Wallet Behaviour Intelligence Service",
        "version": "wallet-behaviour-v2",
        "input": "mainnet CKB address",
        "output": "V2 features, support/evidence states, and descriptive behaviour rules",
        "identity_claims": False,
        "modes": {
            "frozen": "Loads an address already represented in the frozen database.",
            "live": "Collects a rolling 30-day mainnet observation through CKB Explorer and runs the V2 behavioral analysis pipeline. Results are bounded by Explorer availability and collection limits; high-volume reliability is not guaranteed.",
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
