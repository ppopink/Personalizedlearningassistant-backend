from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.schemas.progress import ProgressUpdateRequest
from app.services.progress_service import (
    get_learning_progress_flow,
    update_learning_progress_flow,
)


router = APIRouter(tags=["progress"])


@router.post("/api/progress/update")
async def update_learning_progress(request: ProgressUpdateRequest, db: Session = Depends(get_db)):
    return update_learning_progress_flow(request, db)


@router.get("/api/progress/{user_id}")
async def get_learning_progress(user_id: str, course_id: Optional[str] = None, db: Session = Depends(get_db)):
    return get_learning_progress_flow(user_id, course_id, db)
