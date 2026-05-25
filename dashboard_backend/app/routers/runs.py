from fastapi import APIRouter

from app.repositories.dashboard import get_runs
from app.schemas.runs import RunResponse


router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=list[RunResponse])
async def read_runs() -> list[RunResponse]:
    return await get_runs()
