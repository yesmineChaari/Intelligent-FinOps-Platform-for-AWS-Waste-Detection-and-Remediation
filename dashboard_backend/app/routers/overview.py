from fastapi import APIRouter

from app.repositories.dashboard import get_overview
from app.schemas.overview import OverviewResponse


router = APIRouter(prefix="/overview", tags=["overview"])


@router.get("", response_model=OverviewResponse)
async def read_overview() -> OverviewResponse:
    return await get_overview()
