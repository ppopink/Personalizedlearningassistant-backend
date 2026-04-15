from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.schemas.tutor import TutorRequest
from app.services.tutor_service import tutor_respond_flow, tutor_stream_flow


router = APIRouter(tags=["tutor"])


@router.post("/api/tutor/respond")
async def tutor_chat(request: TutorRequest, db: Session = Depends(get_db)):
    return tutor_respond_flow(request, db)


@router.post("/api/study/tutor-chat/stream")
async def tutor_chat_stream(request: TutorRequest, db: Session = Depends(get_db)):
    return tutor_stream_flow(request, db)
