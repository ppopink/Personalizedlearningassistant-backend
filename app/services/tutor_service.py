import asyncio
from typing import Any, Dict, Optional

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import client
from app.db.models import UserCognitiveProfile, UserSyllabus
from app.schemas.tutor import TutorRequest
from app.services.common_service import ensure_list
from app.services.course_service import resolve_tutor_section_context


def normalize_thinking_script(
    raw_profile: Optional[Dict[str, Any]],
    learner_profile: Optional[Dict[str, Any]],
    difficulty_preference: Optional[str] = None,
):
    raw_profile = raw_profile if isinstance(raw_profile, dict) else {}
    learner_profile = learner_profile if isinstance(learner_profile, dict) else {}

    preferred_styles = (
        ensure_list(raw_profile.get("preferred_explanation_styles"))
        or ensure_list(raw_profile.get("preferred_style"))
        or ensure_list(learner_profile.get("preferred_style"))
    )
    reasoning_preferences = ensure_list(raw_profile.get("reasoning_preferences")) or preferred_styles
    motivation_hooks = (
        ensure_list(raw_profile.get("motivation_hooks"))
        or ensure_list(learner_profile.get("learning_goal"))
        or ensure_list(learner_profile.get("motivation"))
    )
    friction_points = (
        ensure_list(raw_profile.get("friction_points"))
        or ensure_list(learner_profile.get("pain_points"))
    )

    return {
        "preferred_explanation_styles": preferred_styles,
        "reasoning_preferences": reasoning_preferences,
        "hint_preference": raw_profile.get("hint_preference") or "渐进式提示",
        "difficulty_preference": difficulty_preference or raw_profile.get("difficulty_preference") or "匹配当前水平",
        "motivation_hooks": motivation_hooks,
        "friction_points": friction_points,
        "response_pacing": raw_profile.get("response_pacing") or "先确认理解，再给一步提示",
        "encouragement_style": raw_profile.get("encouragement_style") or "具体指出用户已经做对的部分",
    }


def load_tutor_thinking_script(
    user_id: Optional[str],
    db: Session,
    learner_profile: Optional[Dict[str, Any]] = None,
    difficulty_preference: Optional[str] = None,
    override_script: Optional[Dict[str, Any]] = None,
):
    if isinstance(override_script, dict):
        return normalize_thinking_script(
            override_script,
            learner_profile,
            difficulty_preference=difficulty_preference,
        ), "request_override"

    if user_id:
        profile_record = db.query(UserCognitiveProfile).filter(
            UserCognitiveProfile.user_id == user_id
        ).first()
        if profile_record and isinstance(profile_record.profile_json, dict):
            return normalize_thinking_script(
                profile_record.profile_json,
                learner_profile,
                difficulty_preference=difficulty_preference,
            ), "database_profile"

    return normalize_thinking_script(
        {},
        learner_profile,
        difficulty_preference=difficulty_preference,
    ), "learner_profile_fallback"


def build_tutor_context(request: TutorRequest, db: Session):
    course_plan = None
    section_context = None

    if request.user_id and request.course_id:
        syllabus_record = db.query(UserSyllabus).filter(
            UserSyllabus.user_id == request.user_id,
            UserSyllabus.course_id == request.course_id,
        ).first()
        if syllabus_record and isinstance(syllabus_record.syllabus_data, dict):
            course_plan = syllabus_record.syllabus_data
            section_context = resolve_tutor_section_context(course_plan, request)

    learner_profile = {}
    if section_context and isinstance(section_context.get("learner_profile"), dict):
        learner_profile = section_context["learner_profile"]

    thinking_script, script_source = load_tutor_thinking_script(
        user_id=request.user_id,
        db=db,
        learner_profile=learner_profile,
        difficulty_preference=request.difficulty_preference,
        override_script=request.thinking_script,
    )

    return {
        "course_plan_found": bool(course_plan),
        "section_context": section_context,
        "learner_profile": learner_profile,
        "thinking_script": thinking_script,
        "thinking_script_source": script_source,
    }


def build_tutor_system_prompt(request: TutorRequest, tutor_context: Dict[str, Any]):
    style_prompts = {
        "鼓励引导型": "语气温柔、鼓励感强，先肯定用户已有进展，再给提示。",
        "精炼直接型": "语气专业、直接、简洁，快速指出关键卡点和下一步。",
        "幽默风趣型": "语气轻松、有类比感和一点幽默，但不能影响清晰度。",
    }
    style_description = style_prompts.get(request.tutor_style, style_prompts["鼓励引导型"])

    section_context = tutor_context.get("section_context") or {}
    chapter = section_context.get("chapter") or {}
    section = section_context.get("section") or {}
    learner_profile = tutor_context.get("learner_profile") or {}
    thinking_script = tutor_context.get("thinking_script") or {}

    return f"""
    你是智能学习平台的“陪伴导师 Agent”。
    你的导师风格是：{request.tutor_style}。风格说明：{style_description}

    【当前课程上下文】
    - 课程：{section_context.get("course_title") or request.course_id or "未提供"}
    - 章节：{chapter.get("title") or request.chapter_title or "未提供"}
    - 小节：{section.get("title") or request.section_title or "未提供"}
    - 小节目标：{section.get("objective") or "未提供"}
    - 当前小节关键点：{", ".join(section.get("key_points", [])) or "未提供"}
    - 当前章节学习目标：{", ".join(chapter.get("learning_goals", [])) or "未提供"}

    【学习者画像】
    - 当前水平：{learner_profile.get("user_level") or "unknown"}
    - 学习目标：{learner_profile.get("learning_goal") or learner_profile.get("motivation") or "未提供"}
    - 已知薄弱点：{", ".join(ensure_list(learner_profile.get("pain_points"))) or "未提供"}
    - 推荐起点：{learner_profile.get("recommended_start_point") or section_context.get("recommended_start_point") or "未提供"}

    【思维方式脚本】
    - 偏好解释方式：{", ".join(thinking_script.get("preferred_explanation_styles", [])) or "未提供"}
    - 推理偏好：{", ".join(thinking_script.get("reasoning_preferences", [])) or "未提供"}
    - 提示偏好：{thinking_script.get("hint_preference") or "渐进式提示"}
    - 难度偏好：{thinking_script.get("difficulty_preference") or "匹配当前水平"}
    - 激励点：{", ".join(thinking_script.get("motivation_hooks", [])) or "未提供"}
    - 容易卡住：{", ".join(thinking_script.get("friction_points", [])) or "未提供"}
    - 响应节奏：{thinking_script.get("response_pacing") or "先确认理解，再给一步提示"}

    【当前题目上下文】
    {request.question_context or "用户暂时没有提供具体题目，只是在围绕当前小节提问。"}

    【用户当前行为】
    {request.user_action or "普通提问"}

    你的核心规则：
    1. 必须使用苏格拉底式教学法，用提问、拆解、类比、局部提示引导用户自己想清楚。
    2. 严禁直接给最终答案、完整可提交代码、完整解题步骤、正确选项字母。
    3. 如果用户要求“直接告诉我答案/代码”，你要简短拒绝，然后给一个最小下一步提示。
    4. 如果用户是知识延伸或概念追问，你可以解释清楚，但结尾要自然拉回当前小节或当前题目。
    5. 解释方式必须优先匹配“思维方式脚本”。如果用户偏好类比，就多用类比；如果偏好先例子后概念，就先给例子。
    6. 当用户卡住时，优先给“一步提示”，不要一次给三四步。
    7. 如果需要涉及代码，只能给局部片段、伪代码或排查方向，不能给完整答案。
    8. 默认使用 Markdown，回复控制在 3 个短段落以内；除非用户明确要求深入展开。
    9. 每次回复最后，尽量给用户一个具体可执行的下一步问题或思考动作。
    """


def build_tutor_messages(request: TutorRequest, tutor_context: Dict[str, Any]):
    system_prompt = build_tutor_system_prompt(request, tutor_context)
    messages = [{"role": "system", "content": system_prompt}]

    if request.question_context or request.user_action:
        messages.append({
            "role": "user",
            "content": (
                f"【题目上下文】\n{request.question_context or '无'}\n\n"
                f"【用户当前行为】\n{request.user_action or '普通提问'}"
            ),
        })

    for msg in request.messages:
        messages.append({"role": msg.role, "content": msg.content})

    return messages


def prepare_tutor_runtime(request: TutorRequest, db: Session):
    tutor_context = build_tutor_context(request, db)
    messages = build_tutor_messages(request, tutor_context)
    return tutor_context, messages


def tutor_respond_flow(request: TutorRequest, db: Session):
    try:
        tutor_context, messages = prepare_tutor_runtime(request, db)
        response = client.chat.completions.create(
            model="qwen-plus",
            messages=messages,
        )

        return {
            "status": "success",
            "reply": response.choices[0].message.content,
            "context": {
                "course_plan_found": tutor_context.get("course_plan_found", False),
                "thinking_script_source": tutor_context.get("thinking_script_source"),
                "learner_profile": tutor_context.get("learner_profile"),
                "section_context": tutor_context.get("section_context"),
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"陪伴导师回复失败: {str(exc)}")


def tutor_stream_flow(request: TutorRequest, db: Session):
    tutor_context, messages = prepare_tutor_runtime(request, db)

    async def generate_response():
        try:
            response = client.chat.completions.create(
                model="qwen-plus",
                messages=messages,
                stream=True,
            )
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    yield f"data: {content}\n\n"
                    await asyncio.sleep(0.01)
        except Exception as exc:
            yield f"data: [Error] 导师掉线了: {str(exc)}\n\n"

    return StreamingResponse(generate_response(), media_type="text/event-stream")
