import re
from typing import Any, Dict, Optional

from fastapi import HTTPException

from app.services.common_service import ensure_list


def is_placeholder_title(value: Any):
    text = str(value or "").strip()
    if not text:
        return True
    lowered = text.lower()
    return "未命名" in text or lowered in {"section", "chapter", "小节", "章节"}


def clean_focus_text(value: Any):
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"^\d+(\.\d+)*\s*", "", text)
    text = text.replace("：", " ").replace(":", " ").strip()
    return text[:40].strip()


def build_fallback_chapter_title(chapter: Dict[str, Any], chapter_index: int, context: Optional[Dict[str, Any]] = None):
    title = str(chapter.get("title") or chapter.get("chapter_title") or "").strip()
    if not is_placeholder_title(title):
        return title

    context = context or {}
    key_topics = context.get("key_topics") or []
    topic = key_topics[chapter_index - 1] if chapter_index - 1 < len(key_topics) else ""
    base = clean_focus_text(topic) or clean_focus_text(context.get("course_title")) or "核心内容"
    return f"第{chapter_index}章：{base}"


def build_fallback_section_title(section: Dict[str, Any], chapter_title: str, chapter_index: int, section_index: int):
    title = str(section.get("title") or section.get("section_title") or "").strip()
    if not is_placeholder_title(title):
        return title

    key_points = ensure_list(section.get("key_points"))
    objective = clean_focus_text(section.get("objective") or section.get("learning_objective"))
    focus = clean_focus_text(key_points[0] if key_points else "") or objective or clean_focus_text(chapter_title) or "核心内容"
    return f"{chapter_index}.{section_index} {focus}"


def build_fallback_objective(section_title: str, chapter_title: str):
    focus = clean_focus_text(section_title) or clean_focus_text(chapter_title) or "当前主题"
    return f"理解 {focus} 的核心概念、关键用法与典型场景"


def build_question_focus(section_title: str, objective: str, key_points: Any):
    points = ensure_list(key_points)
    return clean_focus_text(points[0] if points else "") or clean_focus_text(section_title) or clean_focus_text(objective) or "当前知识点"


def build_fallback_question_payloads(
    chapter_title: str,
    section_title: str,
    objective: str,
    key_points: Any,
    required_count: int,
):
    focus = build_question_focus(section_title, objective, key_points)
    templates = [
        {
            "type": "choice",
            "question": f"下面哪项最符合“{focus}”这一小节的学习重点？",
            "options": [
                {"label": "A", "text": "理解核心概念、作用和基本使用场景"},
                {"label": "B", "text": "跳过概念，直接背诵所有细节"},
                {"label": "C", "text": "只关注历史背景，不看实际用途"},
                {"label": "D", "text": "只记结论，不理解为什么"},
            ],
            "answer": "A",
            "explanation": f"本节应先建立对“{focus}”的概念理解，再进入应用。",
            "hint": f"回想小节标题“{section_title}”和学习目标。",
        },
        {
            "type": "short_answer",
            "question": f"请用自己的话说明“{focus}”是什么，它主要解决了什么问题？",
            "answer": f"答案应覆盖“{focus}”的核心概念、主要作用和适用场景。",
            "explanation": f"这道题用来检查你是否真正理解了“{focus}”的含义，而不是只记住名词。",
            "hint": "可以从“它是什么、为什么需要它、什么时候会用到它”三个角度回答。",
        },
        {
            "type": "fill",
            "question": f"学习“{focus}”时，至少要搞清楚它的 ____ 、 ____ 和基本使用场景。",
            "answer": "核心概念,主要作用",
            "explanation": f"理解“{focus}”时，先抓住概念和作用，再联系场景会更稳。",
            "hint": "想想入门一个新知识点时最先要确认的两个方面。",
        },
    ]

    return [templates[index % len(templates)] for index in range(max(required_count, 1))]


def normalize_question_node(question: Any, chapter_index: int, section_index: int, question_index: int):
    question = question or {}
    question_type = str(question.get("type") or "short_answer").strip().lower()
    if question_type not in {"choice", "fill", "short_answer"}:
        question_type = "short_answer"

    normalized_question = {
        "id": question.get("id") or f"q_{chapter_index}_{section_index}_{question_index}",
        "type": question_type,
        "question": str(question.get("question") or "").strip(),
        "answer": str(question.get("answer") or "").strip(),
        "explanation": str(question.get("explanation") or "").strip(),
        "hint": str(question.get("hint") or "").strip(),
    }

    if question_type == "choice":
        normalized_question["options"] = normalize_question_options(question.get("options"))

    return normalized_question


def normalize_question_options(options: Any):
    if not isinstance(options, list):
        return []

    normalized_options = []
    for index, option in enumerate(options):
        if isinstance(option, dict):
            label = str(option.get("label") or chr(65 + index))
            text = str(option.get("text") or option.get("content") or "").strip()
        else:
            label = chr(65 + index)
            text = str(option).strip()

        if text:
            normalized_options.append({"label": label, "text": text})

    return normalized_options


def normalize_course_section_node(section: Any, chapter_index: int, section_index: int):
    if not isinstance(section, dict):
        section = {"title": str(section).strip()}

    chapter_title = f"第{chapter_index}章"
    title = build_fallback_section_title(section, chapter_title, chapter_index, section_index)
    objective = str(section.get("objective") or section.get("learning_objective") or "").strip()
    if not objective:
        objective = build_fallback_objective(title, chapter_title)

    if isinstance(section, dict):
        return {
            "id": section.get("id") or f"section_{chapter_index}_{section_index}",
            "title": title,
            "objective": objective,
            "key_points": ensure_list(section.get("key_points")),
            "practice_questions": section.get("practice_questions") or section.get("questions") or [],
        }


def normalize_course_chapter_node(chapter: Any, chapter_index: int, context: Optional[Dict[str, Any]] = None):
    if not isinstance(chapter, dict):
        chapter = {}

    sections_raw = chapter.get("sections") or []
    chapter_title = build_fallback_chapter_title(chapter, chapter_index, context)
    sections = [
        normalize_course_section_node(section, chapter_index, section_index)
        for section_index, section in enumerate(sections_raw, start=1)
    ]

    return {
        "id": chapter.get("id") or f"chapter_{chapter_index}",
        "title": chapter_title,
        "description": str(chapter.get("description") or "").strip(),
        "learning_goals": ensure_list(chapter.get("learning_goals")),
        "sections": sections,
    }


def normalize_full_course_plan(course_plan: Any, context: Optional[Dict[str, Any]] = None):
    if not isinstance(course_plan, dict):
        return None

    chapters_raw = course_plan.get("chapters") or []
    normalized_chapters = [
        normalize_course_chapter_node(chapter, chapter_index, context)
        for chapter_index, chapter in enumerate(chapters_raw, start=1)
    ]

    return {
        "title": str(course_plan.get("title") or course_plan.get("course_title") or "").strip(),
        "description": str(course_plan.get("description") or "").strip(),
        "learner_profile": course_plan.get("learner_profile") if isinstance(course_plan.get("learner_profile"), dict) else {},
        "recommended_start_point": str(course_plan.get("recommended_start_point") or "").strip(),
        "course_objectives": ensure_list(course_plan.get("course_objectives")),
        "chapters": normalized_chapters,
    }


def match_course_node(target: Optional[str], *candidates: Optional[str]):
    if not target:
        return False

    normalized_target = str(target).strip().lower()
    for candidate in candidates:
        if candidate and str(candidate).strip().lower() == normalized_target:
            return True
    return False


def resolve_tutor_section_context(course_plan: Optional[Dict[str, Any]], request: Any):
    if not course_plan:
        return None

    normalized_plan = normalize_full_course_plan(course_plan)
    if not normalized_plan:
        return None

    selected_chapter = None
    selected_section = None

    for chapter in normalized_plan["chapters"]:
        chapter_match = match_course_node(getattr(request, "chapter_id", None), chapter.get("id")) or match_course_node(
            getattr(request, "chapter_title", None), chapter.get("title")
        )

        for section in chapter.get("sections", []):
            section_match = match_course_node(getattr(request, "section_id", None), section.get("id")) or match_course_node(
                getattr(request, "section_title", None), section.get("title")
            )

            if section_match:
                selected_chapter = chapter
                selected_section = section
                break

        if selected_section:
            break

        if chapter_match:
            selected_chapter = chapter

    if selected_chapter and not selected_section and selected_chapter.get("sections"):
        selected_section = selected_chapter["sections"][0]

    if not selected_chapter and normalized_plan["chapters"]:
        selected_chapter = normalized_plan["chapters"][0]
        if selected_chapter.get("sections"):
            selected_section = selected_chapter["sections"][0]

    return {
        "course_title": normalized_plan.get("title"),
        "course_description": normalized_plan.get("description"),
        "course_objectives": normalized_plan.get("course_objectives", []),
        "recommended_start_point": normalized_plan.get("recommended_start_point"),
        "learner_profile": normalized_plan.get("learner_profile", {}),
        "chapter": selected_chapter,
        "section": selected_section,
    }


def normalize_course_plan(
    raw_plan: Dict[str, Any],
    context: Dict[str, Any],
    interview_payload: Dict[str, Any],
    interview_session_id: Optional[str] = None,
    questions_per_section: int = 2,
):
    if not isinstance(raw_plan, dict):
        raise HTTPException(status_code=500, detail="课程架构师返回的数据格式不正确")

    chapters_raw = raw_plan.get("chapters") or []
    if not isinstance(chapters_raw, list) or not chapters_raw:
        raise HTTPException(status_code=500, detail="课程架构师未返回有效章节结构")

    learner_profile = interview_payload.get("interview_summary", {})
    normalized_chapters = []

    for chapter_index, chapter in enumerate(chapters_raw, start=1):
        chapter = chapter or {}
        chapter_title = build_fallback_chapter_title(chapter, chapter_index, context)
        sections_raw = chapter.get("sections") or []
        normalized_sections = []

        for section_index, section in enumerate(sections_raw, start=1):
            if not isinstance(section, dict):
                section = {"title": str(section).strip()}
            section = section or {}
            section_title = build_fallback_section_title(section, chapter_title, chapter_index, section_index)
            section_objective = str(section.get("objective") or section.get("learning_objective") or "").strip()
            if not section_objective:
                section_objective = build_fallback_objective(section_title, chapter_title)
            section_key_points = ensure_list(section.get("key_points"))
            questions_raw = (
                section.get("practice_questions")
                or section.get("questions")
                or []
            )

            normalized_questions = []
            for question_index, question in enumerate(questions_raw, start=1):
                normalized_question = normalize_question_node(question, chapter_index, section_index, question_index)
                if not normalized_question["question"]:
                    continue
                normalized_questions.append(normalized_question)

            required_question_count = max(int(questions_per_section or 0), 1)
            if len(normalized_questions) < required_question_count:
                fallback_questions = build_fallback_question_payloads(
                    chapter_title=chapter_title,
                    section_title=section_title,
                    objective=section_objective,
                    key_points=section_key_points,
                    required_count=required_question_count - len(normalized_questions),
                )
                for offset, question in enumerate(fallback_questions, start=len(normalized_questions) + 1):
                    normalized_questions.append(
                        normalize_question_node(question, chapter_index, section_index, offset)
                    )

            normalized_sections.append({
                "id": section.get("id") or f"section_{chapter_index}_{section_index}",
                "title": section_title,
                "objective": section_objective,
                "key_points": section_key_points,
                "practice_questions": normalized_questions,
            })

        normalized_chapters.append({
            "id": chapter.get("id") or f"chapter_{chapter_index}",
            "title": chapter_title,
            "description": str(chapter.get("description") or "").strip(),
            "learning_goals": ensure_list(chapter.get("learning_goals")),
            "sections": normalized_sections,
        })

    return {
        "title": str(raw_plan.get("title") or context.get("course_title") or context.get("course_id")).strip(),
        "description": str(raw_plan.get("description") or raw_plan.get("course_description") or "").strip(),
        "course_id": context.get("course_id"),
        "course_type": context.get("course_type"),
        "recommended_start_point": raw_plan.get("recommended_start_point")
        or learner_profile.get("recommended_start_point")
        or "",
        "course_objectives": ensure_list(raw_plan.get("course_objectives")),
        "learner_profile": learner_profile,
        "interview_session_id": interview_session_id,
        "chapters": normalized_chapters,
        "metadata": {
            "agent": "architect",
            "version": "v1",
            "question_count": sum(
                len(section.get("practice_questions", []))
                for chapter in normalized_chapters
                for section in chapter.get("sections", [])
            ),
        },
    }
