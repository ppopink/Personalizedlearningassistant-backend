import json
from typing import Any, Dict, List

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import client
from app.db.models import CognitiveProfileObservation, UserNote, UserSyllabus
from app.schemas.clerk import ClerkGenerateNoteRequest
from app.schemas.common import ChatMessage
from app.services.common_service import parse_json_response
from app.services.course_service import normalize_full_course_plan, resolve_tutor_section_context
from app.services.tutor_service import load_tutor_thinking_script


def resolve_clerk_context(request: ClerkGenerateNoteRequest, db: Session):
    syllabus_record = db.query(UserSyllabus).filter(
        UserSyllabus.user_id == request.user_id,
        UserSyllabus.course_id == request.course_id,
    ).first()

    if not syllabus_record or not isinstance(syllabus_record.syllabus_data, dict):
        raise HTTPException(status_code=404, detail="未找到该课程的课程蓝图，请先完成 Agent 2")

    course_plan = syllabus_record.syllabus_data
    section_context = resolve_tutor_section_context(course_plan, request)
    normalized_plan = normalize_full_course_plan(course_plan) or {}

    learner_profile = {}
    if section_context and isinstance(section_context.get("learner_profile"), dict):
        learner_profile = section_context.get("learner_profile") or {}

    thinking_script, script_source = load_tutor_thinking_script(
        user_id=request.user_id,
        db=db,
        learner_profile=learner_profile,
    )

    observations_query = db.query(CognitiveProfileObservation).filter(
        CognitiveProfileObservation.user_id == request.user_id
    )
    if request.course_id:
        observations_query = observations_query.filter(
            CognitiveProfileObservation.course_id == request.course_id
        )
    if request.section_id:
        observations_query = observations_query.filter(
            CognitiveProfileObservation.section_id == request.section_id
        )

    observations = observations_query.order_by(
        CognitiveProfileObservation.created_at.desc(),
        CognitiveProfileObservation.id.desc(),
    ).limit(6).all()

    chapter = (section_context or {}).get("chapter") or {}
    section = (section_context or {}).get("section") or {}
    practice_questions = section.get("practice_questions") or []

    return {
        "course_plan": normalized_plan,
        "section_context": section_context,
        "chapter": chapter,
        "section": section,
        "learner_profile": learner_profile,
        "thinking_script": thinking_script,
        "thinking_script_source": script_source,
        "recent_observations": [
            item.observation_json for item in observations
            if isinstance(item.observation_json, dict)
        ],
        "practice_questions": practice_questions,
    }


def build_clerk_message_digest(messages: List[ChatMessage], limit: int = 8):
    digest = []
    for msg in messages[-limit:]:
        role = "用户" if msg.role == "user" else "导师" if msg.role == "assistant" else msg.role
        digest.append(f"{role}: {msg.content}")
    return digest


def build_clerk_note_prompt(request: ClerkGenerateNoteRequest, clerk_context: Dict[str, Any]):
    chapter = clerk_context.get("chapter") or {}
    section = clerk_context.get("section") or {}
    learner_profile = clerk_context.get("learner_profile") or {}
    thinking_script = clerk_context.get("thinking_script") or {}
    recent_observations = clerk_context.get("recent_observations") or []
    practice_questions = clerk_context.get("practice_questions") or []

    observation_summaries = [
        item.get("summary")
        for item in recent_observations
        if isinstance(item, dict) and item.get("summary")
    ]

    practice_question_briefs = []
    for question in practice_questions[:4]:
        if isinstance(question, dict) and question.get("question"):
            practice_question_briefs.append(question.get("question"))

    transcript_digest = build_clerk_message_digest(request.messages)

    system_prompt = f"""
    你是智能学习平台的“笔记整理员 Agent”。

    你的任务：
    1. 根据当前课程章节、小节、用户最近提问、认知画像和陪伴过程，生成一份高质量的 AI 智能笔记。
    2. 笔记必须帮助用户“回顾核心结构 + 看清自己的易错点 + 知道下一步怎么学”。
    3. 你必须让内容贴合学习者画像和思维方式脚本，不要写成空泛教程。

    输出要求：
    - 必须输出合法 JSON，不要使用 Markdown 包裹 JSON。
    - JSON 结构如下：
      {{
        "title": "笔记标题",
        "content": "Markdown 正文，末尾包含 mermaid mindmap 代码块"
      }}
    - `content` 必须使用 Markdown。
    - 结构至少包含以下部分：
      1. `### 本章核心结构`
      2. `### 当前小节精华`
      3. `### 这次学习里的易错点`
      4. `### 下一步行动`
    - {"必须在文末附上 Mermaid mindmap 代码块。" if request.include_mindmap else "可以不生成 Mermaid mindmap。"}
    - 如果生成 Mermaid mindmap，必须严格遵守：
      1. 代码块以 ```mermaid 开头。
      2. 使用 `mindmap`。
      3. 节点内容要兼容 Mermaid 渲染，必要时使用双引号包裹。
      4. 保持层级清晰，不要太深。
    - 笔记语言要清晰、具体、有陪伴感，但不要啰嗦。
    - 内容中要体现用户偏好的讲解方式，例如类比、先例子后概念、一步提示等。
    """

    user_prompt = json.dumps(
        {
            "course": {
                "course_id": request.course_id,
                "course_title": (clerk_context.get("course_plan") or {}).get("title"),
                "chapter": chapter,
                "section": section,
            },
            "learner_profile": learner_profile,
            "thinking_script": thinking_script,
            "recent_observation_summaries": observation_summaries,
            "practice_questions": practice_question_briefs,
            "focus_questions": request.focus_questions,
            "user_takeaways": request.user_takeaways,
            "additional_context": request.additional_context,
            "recent_dialogue_digest": transcript_digest,
        },
        ensure_ascii=False,
    )

    return system_prompt, user_prompt


def build_default_note_title(request: ClerkGenerateNoteRequest, clerk_context: Dict[str, Any]):
    course_title = ((clerk_context.get("course_plan") or {}).get("title") or request.course_id or "课程").strip()
    chapter = clerk_context.get("chapter") or {}
    section = clerk_context.get("section") or {}

    if section.get("title"):
        return f"{course_title} - {section.get('title')} 学习笔记"
    if chapter.get("title"):
        return f"{course_title} - {chapter.get('title')} 复盘笔记"
    return f"{course_title} 智能学习笔记"


def generate_clerk_note_flow(request: ClerkGenerateNoteRequest, db: Session):
    clerk_context = resolve_clerk_context(request, db)
    system_prompt, user_prompt = build_clerk_note_prompt(request, clerk_context)

    try:
        response = client.chat.completions.create(
            model="qwen-plus",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )

        note_payload = parse_json_response(response.choices[0].message.content)
        title = str(note_payload.get("title") or request.note_title or build_default_note_title(request, clerk_context)).strip()
        content = str(note_payload.get("content") or "").strip()

        if not content:
            raise HTTPException(status_code=500, detail="Agent 5 未返回有效笔记内容")

        saved_note_id = None
        if request.auto_save:
            new_note = UserNote(
                user_id=request.user_id,
                course_id=request.course_id,
                title=title,
                content=content,
            )
            db.add(new_note)
            db.flush()
            saved_note_id = new_note.id
            db.commit()
        else:
            db.rollback()

        return {
            "status": "success",
            "message": "笔记整理员已完成本次智能笔记生成",
            "data": {
                "title": title,
                "content": content,
                "saved_note_id": saved_note_id,
            },
            "context": {
                "section_context": clerk_context.get("section_context"),
                "thinking_script_source": clerk_context.get("thinking_script_source"),
                "recent_observation_count": len(clerk_context.get("recent_observations", [])),
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"生成智能笔记失败: {str(exc)}")
