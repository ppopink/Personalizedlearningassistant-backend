from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.schemas.architect import ArchitectGenerateRequest
from app.services.architect_service import generate_course_plan_flow


router = APIRouter(tags=["architect"])


@router.post("/api/architect/generate-course-plan")
async def generate_course_plan(request: ArchitectGenerateRequest, db: Session = Depends(get_db)):
    return generate_course_plan_flow(request, db)
