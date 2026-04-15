import json
from typing import Any, Dict, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import client
from app.db.models import User, UserCognitiveProfile, UserNote, UserSyllabus
from app.schemas.concierge import ConciergeRequest
from app.services.common_service import parse_json_response
from app.services.progress_service import (
    build_user_progress_overview,
)


def build_concierge_snapshot(user_id: str, db: Session):
    user = db.query(User).filter(User.username == user_id).first()
    notes = db.query(UserNote).filter(
        UserNote.user_id == user_id
    ).order_by(UserNote.created_at.desc()).limit(5).all()
    courses = db.query(UserSyllabus).filter(
        UserSyllabus.user_id == user_id
    ).all()
    progress_overview = build_user_progress_overview(user_id, db)
    cognitive_profile = db.query(UserCognitiveProfile).filter(
        UserCognitiveProfile.user_id == user_id
    ).first()

    course_summaries = []
    for course in courses:
        syllabus = course.syllabus_data if isinstance(course.syllabus_data, dict) else {}
        title = syllabus.get("title") or syllabus.get("course_title") or course.course_id
        course_summaries.append({
            "course_id": course.course_id,
            "title": title,
        })

    return {
        "user": {
            "username": user.username if user else user_id,
            "background": user.background if user else None,
            "daily_goal_minutes": user.daily_goal_minutes if user else None,
        },
        "courses": course_summaries,
        "progress_overview": progress_overview,
        "recent_notes": [
            {
                "id": note.id,
                "course_id": note.course_id,
                "title": note.title,
                "created_at": note.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            }
            for note in notes
        ],
        "cognitive_profile": cognitive_profile.profile_json if cognitive_profile and isinstance(cognitive_profile.profile_json, dict) else None,
    }


def detect_frontend_action(message: str, snapshot: Dict[str, Any]):
    text = (message or "").lower()

    if any(keyword in text for keyword in ["暗黑", "深色", "夜间模式", "dark mode", "dark"]):
        return {
            "type": "set_theme",
            "payload": {"theme": "dark"},
        }
    if any(keyword in text for keyword in ["浅色", "亮色", "light mode", "light"]):
        return {
            "type": "set_theme",
            "payload": {"theme": "light"},
        }
    if any(keyword in text for keyword in ["笔记", "note"]):
        return {
            "type": "navigate",
            "payload": {"target": "notes"},
        }
    if any(keyword in text for keyword in ["课程", "继续学习", "打开课程", "回到课程"]):
        progress_overview = snapshot.get("progress_overview") or []
        if progress_overview:
            first_course = progress_overview[0]
            payload = {
                "target": "course",
                "course_id": first_course.get("course_id"),
            }
            progress = first_course.get("progress") or {}
            if progress.get("current_section_id"):
                payload["section_id"] = progress.get("current_section_id")
            return {
                "type": "navigate",
                "payload": payload,
            }

    return None


def detect_concierge_route(message: str):
    text = (message or "").lower()

    if any(keyword in text for keyword in ["进度", "学到哪", "学习进展", "完成多少", "progress"]):
        return "learning_progress"
    if any(keyword in text for keyword in ["暗黑", "深色", "浅色", "主题", "theme"]):
        return "platform_navigation"
    if any(keyword in text for keyword in ["笔记", "note"]):
        return "notes_navigation"
    if any(keyword in text for keyword in ["课程", "继续学习", "打开课程", "回到课程"]):
        return "course_navigation"
    if any(keyword in text for keyword in ["怎么用", "在哪里", "不会操作", "操作", "平台"]):
        return "platform_help"
    return "general_support"


def build_progress_reply(snapshot: Dict[str, Any]):
    progress_overview = snapshot.get("progress_overview") or []
    if not progress_overview:
        return "你还没有可用的学习进度记录。等前端开始上报当前章节和完成情况后，我就能更准确地告诉你学到哪了。"

    first_course = progress_overview[0]
    progress = first_course.get("progress") or {}
    course_title = first_course.get("course_title") or first_course.get("course_id")
    current_section = progress.get("current_section_title") or "还没记录当前小节"
    section_progress = progress.get("section_progress_percent", 0)

    return (
        f"你当前最近在学《{course_title}》。"
        f" 已完成 {progress.get('completed_section_count', 0)}/{progress.get('section_total', 0)} 个小节，"
        f"约 {section_progress}% 进度。"
        f" 目前定位在：{current_section}。"
    )


def build_concierge_rule_response(route: str, snapshot: Dict[str, Any], frontend_action: Optional[Dict[str, Any]]):
    action = frontend_action or {"type": "none", "payload": {}}

    if action.get("type") == "set_theme":
        theme = (action.get("payload") or {}).get("theme")
        theme_text = "暗黑模式" if theme == "dark" else "浅色模式" if theme == "light" else "新的主题"
        return {
            "reply": f"我已经帮你准备切到{theme_text}了。",
            "route": "platform_navigation",
            "suggested_frontend_action": action,
        }

    if route == "notes_navigation":
        return {
            "reply": "我可以带你去笔记区，看看最近整理过的学习笔记。",
            "route": route,
            "suggested_frontend_action": action if action.get("type") != "none" else {
                "type": "navigate",
                "payload": {"target": "notes"},
            },
        }

    if route == "course_navigation":
        progress_overview = snapshot.get("progress_overview") or []
        if progress_overview:
            course = progress_overview[0]
            progress = course.get("progress") or {}
            return {
                "reply": f"我可以带你回到《{course.get('course_title') or course.get('course_id')}》，从 {progress.get('current_section_title') or '当前学习位置'} 继续。",
                "route": route,
                "suggested_frontend_action": action if action.get("type") != "none" else {
                    "type": "navigate",
                    "payload": {
                        "target": "course",
                        "course_id": course.get("course_id"),
                        "section_id": progress.get("current_section_id"),
                    },
                },
            }

    return None


def build_concierge_llm_response(request: ConciergeRequest, snapshot: Dict[str, Any], route: str, frontend_action: Optional[Dict[str, Any]]):
    system_prompt = """
    你是智能学习平台的“全局助手 Agent / Concierge”。

    你的任务：
    1. 根据用户消息和平台快照，给出简洁、友好、可执行的回复。
    2. 你是平台路由器，不负责深入讲课；如果用户是要继续学习、看进度、看笔记、切换主题、找功能入口，你要优先帮助他导航。
    3. 如果已经有明确 route 或 frontend_action，请围绕它回复，不要跑题。
    4. 回复尽量短，1 到 3 句话即可。

    输出必须是合法 JSON：
    {
      "reply": "给用户看的自然语言回复",
      "route": "learning_progress|platform_navigation|notes_navigation|course_navigation|platform_help|general_support",
      "suggested_frontend_action": {
        "type": "navigate|set_theme|none",
        "payload": {}
      }
    }
    """

    user_prompt = json.dumps(
        {
            "message": request.message,
            "current_page": request.current_page,
            "route_hint": route,
            "frontend_action_hint": frontend_action,
            "snapshot": snapshot,
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


def concierge_respond_flow(request: ConciergeRequest, db: Session):
    snapshot = build_concierge_snapshot(request.user_id, db)
    route = detect_concierge_route(request.message)
    frontend_action = detect_frontend_action(request.message, snapshot) if request.allow_frontend_actions else None

    try:
        if route == "learning_progress":
            reply = build_progress_reply(snapshot)
            response_payload = {
                "reply": reply,
                "route": route,
                "suggested_frontend_action": frontend_action or {"type": "none", "payload": {}},
            }
        else:
            response_payload = build_concierge_rule_response(route, snapshot, frontend_action)
            if not response_payload:
                response_payload = build_concierge_llm_response(
                    request=request,
                    snapshot=snapshot,
                    route=route,
                    frontend_action=frontend_action,
                )

        action = response_payload.get("suggested_frontend_action") if isinstance(response_payload, dict) else None
        if not isinstance(action, dict):
            action = frontend_action or {"type": "none", "payload": {}}

        return {
            "status": "success",
            "data": {
                "reply": response_payload.get("reply") if isinstance(response_payload, dict) else "",
                "route": response_payload.get("route") if isinstance(response_payload, dict) else route,
                "frontend_action": action,
                "snapshot": {
                    "courses": snapshot.get("courses", []),
                    "progress_overview": snapshot.get("progress_overview", []),
                    "recent_notes": snapshot.get("recent_notes", []),
                },
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"全局助手响应失败: {str(exc)}")
