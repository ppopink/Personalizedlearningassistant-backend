from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.schemas.profiler import ProfilerAnalyzeRequest
from app.services.profiler_service import (
    analyze_learning_interaction_flow,
    get_cognitive_profile_flow,
)


router = APIRouter(tags=["profiler"])


@router.post("/api/profiler/analyze-interaction")
async def analyze_learning_interaction(request: ProfilerAnalyzeRequest, db: Session = Depends(get_db)):
    return analyze_learning_interaction_flow(request, db)


@router.get("/api/profiler/profile/{user_id}")
async def get_cognitive_profile(user_id: str, db: Session = Depends(get_db)):
    return get_cognitive_profile_flow(user_id, db)
