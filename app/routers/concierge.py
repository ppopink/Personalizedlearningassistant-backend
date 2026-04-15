from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.schemas.concierge import ConciergeRequest
from app.services.concierge_service import concierge_respond_flow


router = APIRouter(tags=["concierge"])


@router.post("/api/concierge/respond")
async def concierge_respond(request: ConciergeRequest, db: Session = Depends(get_db)):
    return concierge_respond_flow(request, db)
