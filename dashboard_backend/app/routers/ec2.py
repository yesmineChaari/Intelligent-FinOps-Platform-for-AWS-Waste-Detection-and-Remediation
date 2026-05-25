from fastapi import APIRouter

from app.repositories.dashboard import get_ec2_findings
from app.schemas.ec2 import Ec2FindingResponse


router = APIRouter(prefix="/ec2/findings", tags=["ec2"])


@router.get("", response_model=list[Ec2FindingResponse])
async def read_ec2_findings() -> list[Ec2FindingResponse]:
    return await get_ec2_findings()
