from fastapi import APIRouter, Query

from app.repositories.dashboard import get_alerts
from app.schemas.alerts import AlertResponse


router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertResponse])
async def read_alerts(limit: int = Query(default=20, ge=1, le=100)) -> list[AlertResponse]:
    return await get_alerts(limit=limit)
