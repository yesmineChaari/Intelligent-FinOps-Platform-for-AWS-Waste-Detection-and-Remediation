from fastapi import APIRouter

from app.repositories.dashboard import get_s3_findings
from app.schemas.s3 import S3FindingResponse


router = APIRouter(prefix="/s3/findings", tags=["s3"])


@router.get("", response_model=list[S3FindingResponse])
async def read_s3_findings() -> list[S3FindingResponse]:
    return await get_s3_findings()
