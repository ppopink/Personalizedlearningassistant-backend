from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import client
from app.db.models import InterviewResult, InterviewSession, UserSyllabus
from app.schemas.architect import ArchitectGenerateRequest
from app.services.common_service import parse_json_response
from app.services.course_service import normalize_course_plan
from app.services.interview_service import (
    build_completion_payload,
    build_default_slot_state,
    get_interview_messages,
)


def resolve_architect_inputs(request: ArchitectGenerateRequest, db: Session):
    session = None
    session_context = {}
    stored_result = None

    if request.interview_session_id:
        session = db.query(InterviewSession).filter(
            InterviewSession.id == request.interview_session_id
        ).first()
        if not session:
            raise HTTPException(status_code=404, detail="关联的访谈会话不存在")

        session_context = session.context_data or {}
        stored_result = db.query(InterviewResult).filter(
            InterviewResult.session_id == request.interview_session_id
        ).first()

    rag_summary = request.rag_summary.model_dump() if request.rag_summary else None
    context = {
        "user_id": request.user_id or session_context.get("user_id"),
        "course_id": request.course_id or session_context.get("course_id"),
        "course_type": request.course_type or session_context.get("course_type") or "standard",
        "course_title": request.course_title or session_context.get("course_title") or request.course_id,
        "course_summary": request.course_summary or session_context.get("course_summary"),
        "key_topics": request.key_topics or session_context.get("key_topics") or [],
        "rag_summary": rag_summary if rag_summary is not None else session_context.get("rag_summary"),
        "architect_config": request.architect_config.model_dump(),
    }

    interview_payload = request.interview_result or (stored_result.result_json if stored_result else None)

    if not interview_payload and session:
        fallback_messages = get_interview_messages(db, session.id)
        interview_payload = build_completion_payload(
            context=session_context or context,
            slot_state=session.slot_state or build_default_slot_state(),
            messages=fallback_messages,
            termination_reason="incomplete_interview",
        )

    if not interview_payload:
        raise HTTPException(
            status_code=400,
            detail="Agent 2 需要 Agent 1 的访谈结果。请传 interview_session_id 或 interview_result。"
        )

    return context, interview_payload, session


def generate_course_plan_flow(request: ArchitectGenerateRequest, db: Session):
    context, interview_payload, session = resolve_architect_inputs(request, db)
    config = request.architect_config.model_dump()

    system_prompt = f"""
    你是智能学习平台的“课程架构师 Agent”。

    你的任务：
    1. 读取课程上下文和访谈结果，把课程结构化为适合前端渲染的学习蓝图。
    2. 必须根据用户基础、目标、痛点和偏好来调整难度和顺序。
    3. 对标准课，优先围绕 key_topics 组织内容。
    4. 对自定义课，优先围绕 rag_summary 中的资料主题和关键词组织内容，不要脱离资料。
    5. 每个章节都要给出学习目标；每个小节都要给出学习目标和练习题。
    6. 必须输出稳定课程目录，不要输出“导师带你学”“自由探索”“先聊聊再看”这类不确定流程。
    7. 每个章节至少 {config["min_sections_per_chapter"]} 个小节，每个小节至少 {config["questions_per_section"]} 道练习题。
    8. 每个小节 title 必须是明确知识点标题，不能留空，不能出现“未命名小节”“第一部分”“模块一”这类空泛命名。
    9. practice_questions 里每一题都必须包含：type、question、answer、explanation、hint；选择题还必须有 options。

    输出必须是合法 JSON 对象，不要包含 Markdown。
    """

    user_prompt = {
        "course_context": context,
        "interview_result": interview_payload,
        "generation_rules": config,
    }

    response = client.chat.completions.create(
        model="qwen-plus",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": __import__("json").dumps(user_prompt, ensure_ascii=False)},
        ],
        response_format={"type": "json_object"},
    )

    raw_plan = parse_json_response(response.choices[0].message.content)
    normalized_plan = normalize_course_plan(
        raw_plan=raw_plan,
        context=context,
        interview_payload=interview_payload,
        interview_session_id=request.interview_session_id,
        questions_per_section=request.architect_config.questions_per_section,
    )

    existing_syllabus = db.query(UserSyllabus).filter(
        UserSyllabus.user_id == context.get("user_id"),
        UserSyllabus.course_id == context.get("course_id"),
    ).first()

    if existing_syllabus:
        existing_syllabus.syllabus_data = normalized_plan
    else:
        db.add(UserSyllabus(
            user_id=context.get("user_id"),
            course_id=context.get("course_id"),
            syllabus_data=normalized_plan,
        ))

    db.commit()

    return {
        "status": "success",
        "message": "课程架构师已完成定制课程蓝图生成",
        "data": normalized_plan,
        "source": {
            "interview_session_id": request.interview_session_id,
            "used_interview_result": True,
            "used_session_context": bool(session),
        },
    }
