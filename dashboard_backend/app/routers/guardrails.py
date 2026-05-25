from fastapi import APIRouter

from app.repositories.dashboard import get_guardrail_results
from app.schemas.guardrails import GuardrailDecisionResponse


router = APIRouter(prefix="/guardrails", tags=["guardrails"])


@router.get("", response_model=list[GuardrailDecisionResponse])
async def read_guardrail_results() -> list[GuardrailDecisionResponse]:
    return await get_guardrail_results()
