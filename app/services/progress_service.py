from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models import UserLearningProgress, UserSyllabus
from app.schemas.progress import ProgressUpdateRequest
from app.services.common_service import ensure_list, merge_unique_items
from app.services.course_service import normalize_full_course_plan


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def build_course_outline_snapshot(course_plan: Optional[Dict[str, Any]]):
    normalized_plan = normalize_full_course_plan(course_plan)
    if not normalized_plan:
        return {
            "course_title": "",
            "chapter_count": 0,
            "section_count": 0,
            "chapters": [],
        }

    chapters = normalized_plan.get("chapters", [])
    section_count = sum(len(chapter.get("sections", [])) for chapter in chapters)
    return {
        "course_title": normalized_plan.get("title") or "",
        "chapter_count": len(chapters),
        "section_count": section_count,
        "chapters": chapters,
    }


def compute_progress_metrics(course_plan: Optional[Dict[str, Any]], progress_record: Optional[UserLearningProgress]):
    outline = build_course_outline_snapshot(course_plan)
    completed_sections = ensure_list(progress_record.completed_section_ids if progress_record else [])
    completed_chapters = ensure_list(progress_record.completed_chapter_ids if progress_record else [])

    section_total = outline["section_count"]
    chapter_total = outline["chapter_count"]
    section_progress = round((len(completed_sections) / section_total) * 100, 1) if section_total else 0.0
    chapter_progress = round((len(completed_chapters) / chapter_total) * 100, 1) if chapter_total else 0.0

    return {
        "course_title": outline["course_title"],
        "chapter_total": chapter_total,
        "section_total": section_total,
        "completed_chapter_count": len(completed_chapters),
        "completed_section_count": len(completed_sections),
        "section_progress_percent": section_progress,
        "chapter_progress_percent": chapter_progress,
        "completed_chapter_ids": completed_chapters,
        "completed_section_ids": completed_sections,
        "current_chapter_id": progress_record.current_chapter_id if progress_record else None,
        "current_chapter_title": progress_record.current_chapter_title if progress_record else None,
        "current_section_id": progress_record.current_section_id if progress_record else None,
        "current_section_title": progress_record.current_section_title if progress_record else None,
        "last_activity_at": progress_record.last_activity_at.strftime("%Y-%m-%d %H:%M:%S")
        if progress_record and progress_record.last_activity_at else None,
    }


def get_course_plan_record(user_id: str, course_id: str, db: Session):
    return db.query(UserSyllabus).filter(
        UserSyllabus.user_id == user_id,
        UserSyllabus.course_id == course_id,
    ).first()


def get_or_create_progress_record(request: ProgressUpdateRequest, db: Session):
    record = db.query(UserLearningProgress).filter(
        UserLearningProgress.user_id == request.user_id,
        UserLearningProgress.course_id == request.course_id,
    ).first()

    if not record:
        record = UserLearningProgress(
            user_id=request.user_id,
            course_id=request.course_id,
            completed_chapter_ids=[],
            completed_section_ids=[],
            progress_json={},
        )
        db.add(record)

    return record


def merge_progress_lists(existing: Any, new_values: List[str]):
    return merge_unique_items(ensure_list(existing), new_values, limit=500)


def build_progress_snapshot(record: UserLearningProgress, metrics: Dict[str, Any], extra_meta: Optional[Dict[str, Any]] = None):
    base_snapshot = {
        "event_type": (extra_meta or {}).get("event_type", "progress_update"),
        "metrics": metrics,
    }
    if extra_meta:
        base_snapshot["meta"] = extra_meta
    record.progress_json = base_snapshot
    return base_snapshot


def build_user_progress_overview(user_id: str, db: Session):
    progress_records = db.query(UserLearningProgress).filter(
        UserLearningProgress.user_id == user_id
    ).order_by(UserLearningProgress.last_activity_at.desc(), UserLearningProgress.id.desc()).all()

    course_items = []
    for record in progress_records:
        course_plan_record = get_course_plan_record(user_id, record.course_id, db)
        course_plan = course_plan_record.syllabus_data if course_plan_record and isinstance(course_plan_record.syllabus_data, dict) else None
        metrics = compute_progress_metrics(course_plan, record)
        course_items.append({
            "course_id": record.course_id,
            "course_title": metrics.get("course_title") or record.course_id,
            "progress": metrics,
        })

    return course_items


def update_learning_progress_flow(request: ProgressUpdateRequest, db: Session):
    try:
        record = get_or_create_progress_record(request, db)
        record.current_chapter_id = request.current_chapter_id or record.current_chapter_id
        record.current_chapter_title = request.current_chapter_title or record.current_chapter_title
        record.current_section_id = request.current_section_id or record.current_section_id
        record.current_section_title = request.current_section_title or record.current_section_title
        record.completed_chapter_ids = merge_progress_lists(
            record.completed_chapter_ids,
            request.completed_chapter_ids,
        )
        record.completed_section_ids = merge_progress_lists(
            record.completed_section_ids,
            request.completed_section_ids,
        )
        record.last_activity_at = utc_now()

        course_plan_record = get_course_plan_record(request.user_id, request.course_id, db)
        course_plan = course_plan_record.syllabus_data if course_plan_record and isinstance(course_plan_record.syllabus_data, dict) else None
        metrics = compute_progress_metrics(course_plan, record)
        progress_snapshot = build_progress_snapshot(
            record,
            metrics,
            extra_meta={
                "event_type": request.event_type,
                "progress_meta": request.progress_meta,
            },
        )

        db.commit()

        return {
            "status": "success",
            "message": "学习进度已更新",
            "data": {
                "course_id": request.course_id,
                "progress": metrics,
                "snapshot": progress_snapshot,
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"更新学习进度失败: {str(exc)}")


def get_learning_progress_flow(user_id: str, course_id: Optional[str], db: Session):
    if course_id:
        record = db.query(UserLearningProgress).filter(
            UserLearningProgress.user_id == user_id,
            UserLearningProgress.course_id == course_id,
        ).first()
        if not record:
            raise HTTPException(status_code=404, detail="未找到该课程的学习进度")

        course_plan_record = get_course_plan_record(user_id, course_id, db)
        course_plan = course_plan_record.syllabus_data if course_plan_record and isinstance(course_plan_record.syllabus_data, dict) else None
        metrics = compute_progress_metrics(course_plan, record)
        return {
            "status": "success",
            "data": {
                "course_id": course_id,
                "progress": metrics,
                "snapshot": record.progress_json,
            },
        }

    return {
        "status": "success",
        "data": build_user_progress_overview(user_id, db),
    }
