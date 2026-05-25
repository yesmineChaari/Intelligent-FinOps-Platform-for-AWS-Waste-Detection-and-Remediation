from fastapi import APIRouter

from app.repositories.dashboard import get_phase3_reviews
from app.schemas.phase3 import Phase3ReviewResponse


router = APIRouter(prefix="/phase3/reviews", tags=["phase3"])


@router.get("", response_model=list[Phase3ReviewResponse])
async def read_phase3_reviews() -> list[Phase3ReviewResponse]:
    return await get_phase3_reviews()
