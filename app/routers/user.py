from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.schemas.user import MasteryUpdateRequest, UserProfileRequest
from app.services.user_service import (
    update_knowledge_mastery_flow,
    update_user_profile_flow,
)


router = APIRouter(tags=["user"])


@router.post("/api/user/profile")
async def update_user_profile(request: UserProfileRequest, db: Session = Depends(get_db)):
    return update_user_profile_flow(request, db)


@router.post("/api/knowledge/update")
async def update_knowledge_mastery(request: MasteryUpdateRequest, db: Session = Depends(get_db)):
    return update_knowledge_mastery_flow(request, db)
