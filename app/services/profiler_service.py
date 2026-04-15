import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import client
from app.db.models import (
    CognitiveProfileObservation,
    UserCognitiveProfile,
    UserSyllabus,
)
from app.schemas.profiler import ProfilerAnalyzeRequest
from app.services.common_service import ensure_list, merge_unique_items, parse_json_response
from app.services.course_service import resolve_tutor_section_context
from app.services.tutor_service import normalize_thinking_script


def utc_now_iso():
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


COGNITIVE_PROFILE_LIST_FIELDS = [
    "preferred_explanation_styles",
    "reasoning_preferences",
    "motivation_hooks",
    "friction_points",
    "confidence_signals",
    "avoid_patterns",
    "effective_analogy_topics",
]

COGNITIVE_PROFILE_SCALAR_FIELDS = [
    "hint_preference",
    "difficulty_preference",
    "response_pacing",
    "encouragement_style",
    "preferred_challenge_mode",
]


def normalize_cognitive_profile(
    raw_profile: Optional[Dict[str, Any]],
    learner_profile: Optional[Dict[str, Any]] = None,
):
    thinker = normalize_thinking_script(raw_profile, learner_profile)
    raw_profile = raw_profile if isinstance(raw_profile, dict) else {}

    return {
        "preferred_explanation_styles": thinker.get("preferred_explanation_styles", []),
        "reasoning_preferences": thinker.get("reasoning_preferences", []),
        "hint_preference": thinker.get("hint_preference"),
        "difficulty_preference": thinker.get("difficulty_preference"),
        "motivation_hooks": thinker.get("motivation_hooks", []),
        "friction_points": thinker.get("friction_points", []),
        "response_pacing": thinker.get("response_pacing"),
        "encouragement_style": thinker.get("encouragement_style"),
        "preferred_challenge_mode": str(raw_profile.get("preferred_challenge_mode") or "").strip(),
        "confidence_signals": ensure_list(raw_profile.get("confidence_signals")),
        "avoid_patterns": ensure_list(raw_profile.get("avoid_patterns")),
        "effective_analogy_topics": ensure_list(raw_profile.get("effective_analogy_topics")),
        "evidence_history": raw_profile.get("evidence_history") if isinstance(raw_profile.get("evidence_history"), list) else [],
        "last_summary": str(raw_profile.get("last_summary") or "").strip(),
        "last_updated_reason": str(raw_profile.get("last_updated_reason") or "").strip(),
        "version": raw_profile.get("version") or "v1",
    }


def resolve_profiler_context(request: ProfilerAnalyzeRequest, db: Session):
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

    learner_profile = request.learner_profile_snapshot if isinstance(request.learner_profile_snapshot, dict) else {}
    if not learner_profile and section_context and isinstance(section_context.get("learner_profile"), dict):
        learner_profile = section_context.get("learner_profile") or {}

    existing_record = db.query(UserCognitiveProfile).filter(
        UserCognitiveProfile.user_id == request.user_id
    ).first()
    existing_profile = existing_record.profile_json if existing_record and isinstance(existing_record.profile_json, dict) else {}

    if isinstance(request.thinking_script_snapshot, dict):
        existing_profile = {**existing_profile, **request.thinking_script_snapshot}

    return {
        "course_plan_found": bool(course_plan),
        "section_context": section_context,
        "learner_profile": learner_profile,
        "existing_profile": normalize_cognitive_profile(existing_profile, learner_profile),
        "existing_record": existing_record,
    }


def build_profiler_transcript(request: ProfilerAnalyzeRequest):
    lines = []

    if request.question_context:
        lines.append(f"[题目上下文] {request.question_context}")
    if request.user_action:
        lines.append(f"[用户当前行为] {request.user_action}")
    if request.tutor_style:
        lines.append(f"[导师风格] {request.tutor_style}")

    for message in request.messages[-8:]:
        role = "用户" if message.role == "user" else "导师" if message.role == "assistant" else message.role
        lines.append(f"{role}: {message.content}")

    if request.user_message:
        lines.append(f"用户最新表达: {request.user_message}")
    if request.tutor_reply:
        lines.append(f"导师最近回复: {request.tutor_reply}")
    if request.user_feedback:
        lines.append(f"用户反馈: {request.user_feedback}")

    return "\n".join(lines)


def analyze_cognitive_profile(
    request: ProfilerAnalyzeRequest,
    profiler_context: Dict[str, Any],
):
    section_context = profiler_context.get("section_context") or {}
    chapter = section_context.get("chapter") or {}
    section = section_context.get("section") or {}

    system_prompt = """
    你是智能学习平台的“思维解析员 Agent”。

    你的任务：
    1. 观察用户和陪伴导师的一次交互，提炼稳定的学习偏好、提示偏好、卡点类型和激励点。
    2. 只有当证据足够明确时才更新用户画像；不要因为一句模糊表达就强行下结论。
    3. 优先识别这些字段：
       - preferred_explanation_styles
       - reasoning_preferences
       - hint_preference
       - difficulty_preference
       - motivation_hooks
       - friction_points
       - response_pacing
       - encouragement_style
       - confidence_signals
       - avoid_patterns
       - effective_analogy_topics
    4. 如果用户明确说“这个类比我听懂了”“这样讲我更能懂”“别直接告诉我答案”之类，这是强信号。
    5. 如果证据不足，should_update 可以为 false，但仍要给 summary。

    输出必须是合法 JSON，格式如下：
    {
      "should_update": true,
      "summary": "一句话总结这次观察",
      "profile_updates": {
        "preferred_explanation_styles": ["类比"],
        "reasoning_preferences": ["先例子后概念"],
        "hint_preference": "一次只给一步提示",
        "difficulty_preference": "从简单到稍难",
        "motivation_hooks": ["工作代码能看懂更有动力"],
        "friction_points": ["抽象概念太多会晕"],
        "response_pacing": "先确认理解，再给一步提示",
        "encouragement_style": "先指出做对的部分再推进",
        "preferred_challenge_mode": "先提示后自行作答",
        "confidence_signals": ["用户明确表示类比讲法有效"],
        "avoid_patterns": ["直接抛抽象定义"],
        "effective_analogy_topics": ["线程池"]
      },
      "evidence": [
        {
          "signal": "用户明确说这个类比听懂了",
          "impact": "强化类比解释方式"
        }
      ],
      "confidence": 0.85
    }

    规则：
    - evidence 必须是简洁的事实描述，不要长篇解释。
    - 如果某字段没有证据，就不要硬填。
    - 返回 JSON 中不要带 Markdown。
    """

    user_prompt = json.dumps(
        {
            "interaction_type": request.interaction_type,
            "course_context": {
                "course_id": request.course_id,
                "chapter": chapter,
                "section": section,
            },
            "learner_profile": profiler_context.get("learner_profile"),
            "existing_profile": profiler_context.get("existing_profile"),
            "transcript": build_profiler_transcript(request),
        },
        ensure_ascii=False,
    )

    response = client.chat.completions.create(
        model="qwen-plus",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )

    return parse_json_response(response.choices[0].message.content)


def merge_cognitive_profile_updates(
    existing_profile: Dict[str, Any],
    analysis_result: Dict[str, Any],
):
    merged = normalize_cognitive_profile(existing_profile)
    profile_updates = analysis_result.get("profile_updates") if isinstance(analysis_result, dict) else {}
    profile_updates = profile_updates if isinstance(profile_updates, dict) else {}

    for field in COGNITIVE_PROFILE_LIST_FIELDS:
        merged[field] = merge_unique_items(
            ensure_list(merged.get(field)),
            ensure_list(profile_updates.get(field)),
        )

    for field in COGNITIVE_PROFILE_SCALAR_FIELDS:
        value = profile_updates.get(field)
        if isinstance(value, str) and value.strip():
            merged[field] = value.strip()

    evidence = analysis_result.get("evidence")
    if isinstance(evidence, list):
        existing_evidence = merged.get("evidence_history") if isinstance(merged.get("evidence_history"), list) else []
        new_evidence = [item for item in evidence if isinstance(item, dict)]
        merged["evidence_history"] = (existing_evidence + new_evidence)[-20:]

    summary = str(analysis_result.get("summary") or "").strip()
    if summary:
        merged["last_summary"] = summary

    merged["last_updated_reason"] = str(analysis_result.get("summary") or "").strip()
    merged["version"] = "v1"
    merged["updated_at"] = utc_now_iso()

    return merged


def analyze_learning_interaction_flow(request: ProfilerAnalyzeRequest, db: Session):
    try:
        profiler_context = resolve_profiler_context(request, db)
        analysis_result = analyze_cognitive_profile(request, profiler_context)

        should_update = bool(analysis_result.get("should_update"))
        existing_profile = profiler_context.get("existing_profile") or {}
        updated_profile = existing_profile

        if should_update:
            updated_profile = merge_cognitive_profile_updates(
                existing_profile,
                analysis_result,
            )

            existing_record = profiler_context.get("existing_record")
            if existing_record:
                existing_record.profile_json = updated_profile
            else:
                db.add(UserCognitiveProfile(
                    user_id=request.user_id,
                    profile_json=updated_profile,
                ))

        observation_payload = {
            "summary": analysis_result.get("summary"),
            "confidence": analysis_result.get("confidence"),
            "should_update": should_update,
            "interaction_type": request.interaction_type,
            "analysis_result": analysis_result,
            "course_context": {
                "course_id": request.course_id,
                "chapter_id": request.chapter_id,
                "section_id": request.section_id,
                "chapter_title": request.chapter_title,
                "section_title": request.section_title,
            },
        }

        db.add(CognitiveProfileObservation(
            user_id=request.user_id,
            course_id=request.course_id,
            chapter_id=request.chapter_id,
            section_id=request.section_id,
            interaction_type=request.interaction_type,
            observation_json=observation_payload,
        ))
        db.commit()

        return {
            "status": "success",
            "message": "思维画像已完成分析",
            "updated": should_update,
            "analysis": analysis_result,
            "profile": updated_profile,
        }
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"思维画像分析失败: {str(exc)}")


def get_cognitive_profile_flow(user_id: str, db: Session):
    profile_record = db.query(UserCognitiveProfile).filter(
        UserCognitiveProfile.user_id == user_id
    ).first()
    if not profile_record:
        raise HTTPException(status_code=404, detail="未找到该用户的思维画像")

    observations = db.query(CognitiveProfileObservation).filter(
        CognitiveProfileObservation.user_id == user_id
    ).order_by(CognitiveProfileObservation.created_at.desc(), CognitiveProfileObservation.id.desc()).limit(10).all()

    return {
        "status": "success",
        "data": {
            "user_id": user_id,
            "profile": profile_record.profile_json,
            "recent_observations": [
                {
                    "id": item.id,
                    "interaction_type": item.interaction_type,
                    "course_id": item.course_id,
                    "chapter_id": item.chapter_id,
                    "section_id": item.section_id,
                    "created_at": item.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "summary": item.observation_json.get("summary") if isinstance(item.observation_json, dict) else None,
                    "should_update": item.observation_json.get("should_update") if isinstance(item.observation_json, dict) else None,
                }
                for item in observations
            ],
        },
    }
