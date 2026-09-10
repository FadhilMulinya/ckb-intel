"""CKB Wallet Behaviour Intelligence Service (V2)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

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


class WalletAnalysisRequest(BaseModel):
    address: str = Field(..., description="Mainnet CKB bech32 address")
    mode: str = Field("frozen", pattern="^(frozen|live)$")


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "healthy", "service": "wallet-behaviour-v2",
            "timestamp": datetime.now(timezone.utc).isoformat()}


@app.post("/analyze")
def analyze(request: WalletAnalysisRequest) -> dict[str, Any]:
    try:
        return service.analyze(request.address, live=request.mode == "live")
    except AnalysisError as exc:
        raise HTTPException(status_code=400 if exc.status == "INVALID_ADDRESS" else 422,
                            detail={"status": exc.status, "message": str(exc)}) from exc


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
            "live": "Returns V2_LIVE_ANALYSIS_NOT_YET_SUPPORTED until V2-compatible collection is wired.",
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
