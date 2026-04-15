import json
import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import client
from app.db.models import InterviewMessage, InterviewResult, InterviewSession
from app.schemas.interview import ReplyInterviewRequest, StartInterviewRequest
from app.services.common_service import ensure_list, parse_json_response


logger = logging.getLogger(__name__)


INTERVIEW_REQUIRED_SLOTS = ["foundation", "goal", "pain_point", "preference"]


def build_default_slot_state():
    return {
        slot: {"status": "missing", "value": None, "evidence": ""}
        for slot in INTERVIEW_REQUIRED_SLOTS
    }


def build_interview_context(request: StartInterviewRequest):
    course_title = request.course_title or request.course_id
    rag_summary = request.rag_summary.model_dump() if request.rag_summary else None
    return {
        "user_id": request.user_id,
        "course_id": request.course_id,
        "course_type": request.course_type,
        "course_title": course_title,
        "course_summary": request.course_summary,
        "key_topics": request.key_topics,
        "rag_summary": rag_summary,
        "history_profile": request.history_profile,
        "interview_config": request.interview_config.model_dump(),
    }


def get_missing_slots(slot_state: Dict[str, Dict[str, Any]]):
    return [
        slot for slot in INTERVIEW_REQUIRED_SLOTS
        if slot_state.get(slot, {}).get("status") != "filled"
    ]


def count_filled_slots(slot_state: Dict[str, Dict[str, Any]]):
    return sum(
        1 for slot in INTERVIEW_REQUIRED_SLOTS
        if slot_state.get(slot, {}).get("status") == "filled"
    )


def normalize_slot_updates(updates: Optional[Dict[str, Any]]):
    normalized = {}
    if not isinstance(updates, dict):
        return normalized

    for slot in INTERVIEW_REQUIRED_SLOTS:
        item = updates.get(slot)
        if not isinstance(item, dict):
            continue

        status = item.get("status", "missing")
        if status != "filled":
            status = "missing"

        normalized[slot] = {
            "status": status,
            "value": item.get("value"),
            "evidence": item.get("evidence", ""),
        }

    return normalized


def merge_slot_state(current_state: Dict[str, Dict[str, Any]], updates: Optional[Dict[str, Any]]):
    merged = json.loads(json.dumps(current_state))
    for slot, item in normalize_slot_updates(updates).items():
        merged[slot] = item
    return merged


def serialize_slot_status(slot_state: Dict[str, Dict[str, Any]]):
    return {
        slot: slot_state.get(slot, {}).get("status", "missing")
        for slot in INTERVIEW_REQUIRED_SLOTS
    }


def user_requested_start(user_message: str):
    triggers = ["直接开始", "开始吧", "直接学", "继续学习", "不用问了", "跳过访谈"]
    return any(token in user_message for token in triggers)


def normalize_reply_text(user_message: str):
    return (user_message or "").strip()


def is_low_signal_reply(user_message: str, slot: Optional[str] = None):
    text = normalize_reply_text(user_message)
    if not text:
        return True

    normalized = text.lower()
    generic_tokens = {"1", "2", "3", "4", "5", "6", "ok", "好的", "行", "嗯", "啊", "额"}
    slot_specific_tokens = {
        "goal": {"都行", "随便", "不知道", "不清楚", "没想好"},
        "pain_point": {"不知道", "不清楚", "没想好"},
        "preference": {"都行", "随便", "不知道", "不清楚"},
    }

    if normalized in generic_tokens:
        return True
    if len(text) <= 1 and normalized not in {"会", "懂"}:
        return True
    return normalized in slot_specific_tokens.get(slot, set())


def build_local_slot_update(slot: Optional[str], user_message: str):
    text = normalize_reply_text(user_message)
    if not slot or is_low_signal_reply(text, slot):
        return {}

    if slot in {"pain_point", "preference"}:
        value = ensure_list(text) or [text]
    else:
        value = text

    return {
        slot: {
            "status": "filled",
            "value": value,
            "evidence": f"fallback_from_user_reply: {text[:120]}",
        }
    }


def pick_next_slot(slot_state: Dict[str, Dict[str, Any]], llm_slot: Optional[str] = None):
    missing_slots = get_missing_slots(slot_state)
    if llm_slot in missing_slots:
        return llm_slot
    return missing_slots[0] if missing_slots else None


def build_question_for_slot(slot: Optional[str], context: Dict[str, Any], include_intro: bool = False):
    if not slot:
        return "我已经基本了解你的情况了，我们准备进入正式学习。"

    course_type = context.get("course_type", "standard")
    course_title = context.get("course_title") or context.get("course_id") or "这门课"
    key_topics = context.get("key_topics") or []
    rag_summary = context.get("rag_summary") or {}
    rag_topic = rag_summary.get("document_topic")
    rag_keywords = rag_summary.get("document_keywords") or []

    topic_hint = "、".join(key_topics[:2]) if key_topics else course_title
    rag_hint = rag_topic or "、".join(rag_keywords[:2]) or course_title

    question_map = {
        "foundation": (
            f"我看到你的资料主要和 {rag_hint} 有关，这部分你之前系统接触过吗？"
            if course_type == "custom"
            else f"你之前系统学过 {course_title} 里像 {topic_hint} 这些内容吗？"
        ),
        "goal": f"你这次学 {course_title}，主要更偏向工作、面试、考试，还是先打基础？",
        "pain_point": (
            f"这份资料里你现在最容易卡住的是 {rag_hint} 里的哪一块？"
            if course_type == "custom"
            else "这门课你现在最容易卡住的是概念理解、做题练习，还是实际应用？"
        ),
        "preference": "你更喜欢哪种讲法：先举例、先讲概念，还是用类比来理解？",
    }

    question = question_map.get(slot, "你可以先说说你现在最想解决的问题吗？")
    if include_intro:
        return f"开始前我先用几个小问题了解一下你的基础，方便后面更贴合你。{question}"
    return question


def build_retry_question_for_slot(slot: Optional[str], context: Dict[str, Any]):
    if not slot:
        return "你可以先说说你现在最想解决的问题。"

    course_title = context.get("course_title") or context.get("course_id") or "这门课"
    retry_map = {
        "foundation": "你可以直接告诉我更接近哪种情况：完全没学过、学过一点，还是学过但忘得差不多了？",
        "goal": f"如果只选一个，你这次学 {course_title} 更想解决的是工作使用、面试准备、考试，还是先打基础？",
        "pain_point": "你现在最卡的一点是什么？比如概念理解、做题，或者实际应用。",
        "preference": "后面我可以按你喜欢的方式讲，你更偏向先例子、先概念，还是用类比？",
    }
    return retry_map.get(slot, "你可以换一种更具体的说法告诉我。")


def get_last_assistant_content(messages):
    for message in reversed(messages):
        if message.role == "assistant":
            return message.content
    return None


def get_interview_messages(db: Session, session_id: str):
    return db.query(InterviewMessage).filter(
        InterviewMessage.session_id == session_id
    ).order_by(InterviewMessage.created_at.asc(), InterviewMessage.id.asc()).all()


def build_interview_trace(messages):
    trace = []
    current_question = None
    for message in messages:
        if message.role == "assistant":
            current_question = message.content
        elif message.role == "user":
            trace.append({
                "question": current_question,
                "answer": message.content,
            })
    return trace


def infer_user_level(foundation_text: Optional[str]):
    text = (foundation_text or "").lower()
    if any(token in text for token in ["零基础", "没学过", "没有学过", "不会", "只知道", "beginner"]):
        return "beginner"
    if any(token in text for token in ["做过项目", "比较熟", "深入", "advanced"]):
        return "advanced"
    if any(token in text for token in ["了解一点", "接触过", "学过一些", "intermediate"]):
        return "intermediate"
    return "unknown"


def build_local_interview_summary(context: Dict[str, Any], slot_state: Dict[str, Dict[str, Any]], messages):
    foundation = slot_state.get("foundation", {}).get("value")
    goal = slot_state.get("goal", {}).get("value")
    pain_point = slot_state.get("pain_point", {}).get("value")
    preference = slot_state.get("preference", {}).get("value")
    course_title = context.get("course_title") or context.get("course_id") or "当前课程"

    pain_points = ensure_list(pain_point)
    return {
        "user_level": infer_user_level(foundation),
        "confidence": round(0.45 + count_filled_slots(slot_state) * 0.12, 2),
        "learning_goal": goal or "待进一步确认",
        "deadline": None,
        "preferred_style": ensure_list(preference),
        "pain_points": pain_points,
        "known_topics": [],
        "unknown_topics": [],
        "motivation": goal or "希望完成当前课程学习",
        "recommended_start_point": pain_points[0] if pain_points else course_title,
        "raw_slot_state": slot_state,
        "message_count": len(messages),
    }


def build_completion_payload(
    context: Dict[str, Any],
    slot_state: Dict[str, Dict[str, Any]],
    messages,
    termination_reason: str,
    llm_summary: Optional[Dict[str, Any]] = None,
):
    summary = llm_summary if isinstance(llm_summary, dict) and llm_summary else build_local_interview_summary(
        context, slot_state, messages
    )
    return {
        "interview_summary": summary,
        "interview_trace": build_interview_trace(messages),
        "termination_reason": termination_reason,
    }


def analyze_interview_turn(
    context: Dict[str, Any],
    slot_state: Dict[str, Dict[str, Any]],
    messages,
    question_count: int,
    max_questions: int,
):
    transcript = [{"role": msg.role, "content": msg.content} for msg in messages]
    system_prompt = """
    你是智能学习平台的“访谈官 Agent”，同时负责做结构化访谈分析。

    你的任务：
    1. 根据课程上下文和完整对话，更新四个槽位：foundation / goal / pain_point / preference。
    2. 只能把明确说出来的信息标记为 filled，不要猜。
    3. 如果信息已经足够，或者用户明确表示要直接开始，可以结束访谈。
    4. 如果还不能结束，只生成下一句单次单问的问题，必须自然、简短、口语化。
    5. 不要讲课，不要给课程方案，不要长篇解释。

    输出必须是合法 JSON。
    """

    user_prompt = json.dumps(
        {
            "course_context": context,
            "current_slots": slot_state,
            "question_count": question_count,
            "max_questions": max_questions,
            "transcript": transcript,
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


def start_interview_flow(request: StartInterviewRequest, db: Session):
    context = build_interview_context(request)
    slot_state = build_default_slot_state()
    session_id = f"iv_{uuid.uuid4().hex[:12]}"
    opening_question = build_question_for_slot("foundation", context, include_intro=True)

    session = InterviewSession(
        id=session_id,
        user_id=request.user_id,
        course_id=request.course_id,
        course_type=request.course_type,
        status="active",
        question_count=1,
        max_questions=request.interview_config.max_questions,
        context_data=context,
        slot_state=slot_state,
    )
    db.add(session)
    db.add(InterviewMessage(session_id=session_id, role="assistant", content=opening_question))
    db.commit()

    return {
        "status": "success",
        "session_id": session_id,
        "agent_reply": opening_question,
        "finished": False,
        "current_slots": serialize_slot_status(slot_state),
    }


def reply_interview_flow(request: ReplyInterviewRequest, db: Session):
    session = db.query(InterviewSession).filter(InterviewSession.id == request.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="访谈会话不存在")

    if session.status == "completed":
        result = db.query(InterviewResult).filter(InterviewResult.session_id == session.id).first()
        return {
            "status": "success",
            "session_id": session.id,
            "agent_reply": "这轮访谈已经结束了，我们可以直接进入课程生成。",
            "finished": True,
            "current_slots": serialize_slot_status(session.slot_state or build_default_slot_state()),
            "interview_result": result.result_json if result else None,
        }

    db.add(InterviewMessage(session_id=session.id, role="user", content=request.user_message))
    db.flush()

    slot_state = session.slot_state or build_default_slot_state()
    current_slot = pick_next_slot(slot_state)
    context = session.context_data or {}
    messages = get_interview_messages(db, session.id)
    last_assistant_content = get_last_assistant_content(messages)

    llm_result = {}
    try:
        llm_result = analyze_interview_turn(
            context=context,
            slot_state=slot_state,
            messages=messages,
            question_count=session.question_count,
            max_questions=session.max_questions,
        )
    except Exception:
        logger.exception("Interview analysis failed for session %s", session.id)
        llm_result = {}

    slot_state = merge_slot_state(slot_state, llm_result.get("slot_updates"))
    if current_slot and slot_state.get(current_slot, {}).get("status") != "filled":
        slot_state = merge_slot_state(slot_state, build_local_slot_update(current_slot, request.user_message))
    session.slot_state = slot_state

    force_finish = user_requested_start(request.user_message)
    model_wants_finish = bool(llm_result.get("should_finish"))
    filled_count = count_filled_slots(slot_state)
    missing_slots = get_missing_slots(slot_state)

    finished = (
        force_finish
        or not missing_slots
        or session.question_count >= session.max_questions
        or (model_wants_finish and filled_count >= 3)
    )

    if force_finish:
        termination_reason = "user_requested_start"
    elif not missing_slots:
        termination_reason = "enough_information"
    elif session.question_count >= session.max_questions:
        termination_reason = "max_questions"
    elif finished:
        termination_reason = llm_result.get("termination_reason") or "enough_information"
    else:
        termination_reason = "needs_more_info"

    if finished:
        assistant_reply = llm_result.get("assistant_reply") or "明白了，我已经了解你的情况了，接下来会按你的基础来安排内容。"
        messages_for_summary = messages + [InterviewMessage(role="assistant", content=assistant_reply)]
        completion_payload = build_completion_payload(
            context=context,
            slot_state=slot_state,
            messages=messages_for_summary,
            termination_reason=termination_reason,
            llm_summary=llm_result.get("interview_summary"),
        )

        db.add(InterviewMessage(session_id=session.id, role="assistant", content=assistant_reply))
        existing_result = db.query(InterviewResult).filter(
            InterviewResult.session_id == session.id
        ).first()
        if existing_result:
            existing_result.result_json = completion_payload
            existing_result.termination_reason = termination_reason
        else:
            db.add(InterviewResult(
                session_id=session.id,
                result_json=completion_payload,
                termination_reason=termination_reason,
            ))

        session.status = "completed"
        db.commit()

        return {
            "status": "success",
            "session_id": session.id,
            "agent_reply": assistant_reply,
            "finished": True,
            "current_slots": serialize_slot_status(slot_state),
            "interview_result": completion_payload,
        }

    next_slot = pick_next_slot(slot_state, llm_result.get("next_question_slot"))
    assistant_reply = llm_result.get("assistant_reply") or build_question_for_slot(next_slot, context)
    if next_slot == current_slot and assistant_reply == last_assistant_content:
        assistant_reply = build_retry_question_for_slot(next_slot, context)
    elif not llm_result.get("assistant_reply") and next_slot == current_slot:
        assistant_reply = build_retry_question_for_slot(next_slot, context)

    session.question_count += 1
    db.add(InterviewMessage(session_id=session.id, role="assistant", content=assistant_reply))
    db.commit()

    return {
        "status": "success",
        "session_id": session.id,
        "agent_reply": assistant_reply,
        "finished": False,
        "current_slots": serialize_slot_status(slot_state),
    }


def get_interview_session_detail_flow(session_id: str, db: Session):
    session = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="访谈会话不存在")

    messages = get_interview_messages(db, session.id)
    result = db.query(InterviewResult).filter(InterviewResult.session_id == session.id).first()

    return {
        "status": "success",
        "data": {
            "session_id": session.id,
            "user_id": session.user_id,
            "course_id": session.course_id,
            "course_type": session.course_type,
            "status": session.status,
            "question_count": session.question_count,
            "max_questions": session.max_questions,
            "context": session.context_data,
            "current_slots": session.slot_state,
            "messages": [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "created_at": msg.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                }
                for msg in messages
            ],
            "interview_result": result.result_json if result else None,
        }
    }
