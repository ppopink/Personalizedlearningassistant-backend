from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.schemas.interview import ReplyInterviewRequest, StartInterviewRequest
from app.services.interview_service import (
    get_interview_session_detail_flow,
    reply_interview_flow,
    start_interview_flow,
)


router = APIRouter(tags=["interview"])


@router.post("/api/interview/start")
async def start_interview(request: StartInterviewRequest, db: Session = Depends(get_db)):
    return start_interview_flow(request, db)


@router.post("/api/interview/reply")
async def reply_interview(request: ReplyInterviewRequest, db: Session = Depends(get_db)):
    return reply_interview_flow(request, db)


@router.get("/api/interview/{session_id}")
async def get_interview_session_detail(session_id: str, db: Session = Depends(get_db)):
    return get_interview_session_detail_flow(session_id, db)

