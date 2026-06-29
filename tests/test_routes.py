from fastapi import APIRouter
from pydantic import BaseModel
from tests.mock_services import mock_analyze_pull_request, mock_adaptive_analyze_pull_request
from constants.messages import MOCK_WEBHOOK_RECEIVED, MOCK_ADAPTIVE_WEBHOOK_RECEIVED

router = APIRouter()

class AdaptivePayload(BaseModel):
    file_count: int

@router.post("/test-webhook")
async def test_webhook():
    """Mock webhook listener for load testing."""
    print(MOCK_WEBHOOK_RECEIVED)
    success = await mock_analyze_pull_request()
    return {"status": "accepted", "mock": True, "success": success}

@router.post("/test-adaptive")
async def test_adaptive(payload: AdaptivePayload):
    """Mock webhook for testing the adaptive review strategy."""
    print(MOCK_ADAPTIVE_WEBHOOK_RECEIVED.format(file_count=payload.file_count))
    success = await mock_adaptive_analyze_pull_request(payload.file_count)
    return {"status": "accepted", "mock": True, "success": success}
