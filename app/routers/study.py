from fastapi import APIRouter

from app.schemas.study import QuestionRequest
from app.services.study_service import generate_questions_flow


router = APIRouter(tags=["study"])


@router.post("/api/study/generate-questions")
async def generate_questions(request: QuestionRequest):
    return generate_questions_flow(request)
