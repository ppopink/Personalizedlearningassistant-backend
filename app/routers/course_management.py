import importlib.util

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.schemas.syllabus import SyllabusRequest
from app.services.course_management_service import (
    delete_custom_course_flow,
    generate_custom_syllabus_flow,
    generate_syllabus_flow,
    get_curriculum_flow,
    get_user_custom_courses_flow,
)


router = APIRouter(tags=["course-management"])
HAS_MULTIPART = importlib.util.find_spec("multipart") is not None


@router.post("/api/onboarding/generate-syllabus")
async def generate_syllabus(request: SyllabusRequest, db: Session = Depends(get_db)):
    return generate_syllabus_flow(request, db)


@router.get("/api/curriculum/{user_id}/{course_id}")
async def get_curriculum(user_id: str, course_id: str, db: Session = Depends(get_db)):
    return get_curriculum_flow(user_id, course_id, db)


@router.get("/api/user/custom-courses/{user_id}")
async def get_user_custom_courses(user_id: str, db: Session = Depends(get_db)):
    return get_user_custom_courses_flow(user_id, db)


@router.delete("/api/user/custom-courses/{course_id}")
async def delete_custom_course(course_id: str, db: Session = Depends(get_db)):
    return delete_custom_course_flow(course_id, db)


if HAS_MULTIPART:
    @router.post("/api/onboarding/generate-custom-syllabus")
    async def generate_custom_syllabus(
        file: UploadFile = File(...),
        course_title: str = Form(...),
        user_profile: str = Form(...),
        db: Session = Depends(get_db),
    ):
        return await generate_custom_syllabus_flow(file, course_title, user_profile, db)
else:
    @router.post("/api/onboarding/generate-custom-syllabus")
    async def generate_custom_syllabus():
        raise HTTPException(
            status_code=503,
            detail="当前环境缺少 python-multipart 依赖，暂时无法处理 PDF 上传。请先安装 python-multipart。",
        )
