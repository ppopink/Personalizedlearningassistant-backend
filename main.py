import os
import json
import uuid
import asyncio
import pdfplumber
from io import BytesIO
from datetime import datetime
from typing import List, Dict, Optional, Any
from fastapi import FastAPI, HTTPException, Depends, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from openai import OpenAI
from sqlalchemy.orm import Session
from database import (
    SessionLocal,
    User,
    KnowledgeMastery,
    UserSyllabus,
    UserNote,
    InterviewSession,
    InterviewMessage,
    InterviewResult,
    UserCognitiveProfile,
    CognitiveProfileObservation,
    UserLearningProgress,
    init_db,
)

# 1. 加载 .env 文件中的环境变量
load_dotenv()

# 获取 API Key (请确保你的 .env 文件里有 QWEN_API_KEY=你的实际key)
QWEN_API_KEY = os.getenv("QWEN_API_KEY")
if not QWEN_API_KEY:
    raise ValueError("未找到 QWEN_API_KEY，请检查 .env 文件配置")

# 2. 初始化 FastAPI 实例
app = FastAPI(title="AI 编程私教 API")

# 配置 CORS：允许本地开发域名和 Vercel 生产域名访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",          # Vite 默认本地端口
        "http://127.0.0.1:5173",          # 备用本地地址
        "https://my-ai-frontend.vercel.app",   # 🚨 请将此处替换为你真实的 Vercel 部署域名！
    ],
    allow_credentials=True,
    allow_methods=["*"],  # 允许的请求方法
    allow_headers=["*"],  # 允许的请求头
)

# 3. 初始化千问客户端 (使用 OpenAI SDK 兼容模式)
client = OpenAI(
    api_key=QWEN_API_KEY,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

# 4. 数据库依赖项
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 在启动时初始化数据库
@app.on_event("startup")
def on_startup():
    init_db()

INTERVIEW_REQUIRED_SLOTS = ["foundation", "goal", "pain_point", "preference"]

# 5. 定义数据格式
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]  # 接收消息列表（历史记录）
    username: str = "default_user"
    current_question: Optional[Dict] = None # 🚨 新增：当前题目上下文
    persona: str = "鼓励型"               # 🚨 新增：导师性格设定

class UserProfileRequest(BaseModel):
    username: str
    background: str
    daily_goal_minutes: int

class MasteryUpdateRequest(BaseModel):
    username: str
    point_name: str
    mastery_score: int
    error_summary: str = ""

# 定义前端传过来的采访总结格式
class SyllabusRequest(BaseModel):
    user_id: str         # 告诉后端这是谁
    course_id: str       # 这是哪门课
    course_name: str     # 例如: "Python 基础"
    user_background: str # 例如: "零基础，喜欢先动手后看理论，每天1小时"

# 定义答题导师接收的数据格式 (支持历史记录和题目上下文)
class TutorRequest(BaseModel):
    messages: List[ChatMessage] # 🚨 核心变化：接收数组（对话历史）
    question_context: str = ""  # 当前这道题的题干和选项
    user_action: str = ""       # 用户的行为
    tutor_style: str = "鼓励引导型"
    user_id: Optional[str] = None
    course_id: Optional[str] = None
    chapter_id: Optional[str] = None
    chapter_title: Optional[str] = None
    section_id: Optional[str] = None
    section_title: Optional[str] = None
    difficulty_preference: Optional[str] = None
    thinking_script: Optional[Dict[str, Any]] = None

# 定义前端传过来的学习情况总结数据
class NoteRequest(BaseModel):
    course_name: str       # 例如："Python 基础"
    learned_topics: str    # 例如："变量与数据类型、运算符"
    weak_points: str       # 例如："经常忘记给字符串加引号"

# 定义脑图提取请求体
class MindmapOnlyRequest(BaseModel):
    content: str  # 用户自己写的笔记内容

# 定义生成题目请求体
class QuestionRequest(BaseModel):
    course_id: str
    section_id: str
    section_title: str

# 🚨 新增：创建笔记请求格式
class CreateNoteRequest(BaseModel):
    user_id: str
    course_id: str
    title: str
    content: str


class RagSummary(BaseModel):
    document_topic: Optional[str] = None
    document_keywords: List[str] = Field(default_factory=list)
    document_abstract: Optional[str] = None


class InterviewConfig(BaseModel):
    max_questions: int = 6
    target_duration_min: int = 3
    ask_one_question_only: bool = True


class StartInterviewRequest(BaseModel):
    user_id: str
    course_id: str
    course_type: str = "standard"
    course_title: Optional[str] = None
    course_summary: Optional[str] = None
    key_topics: List[str] = Field(default_factory=list)
    rag_summary: Optional[RagSummary] = None
    history_profile: Dict[str, Any] = Field(default_factory=dict)
    interview_config: InterviewConfig = Field(default_factory=InterviewConfig)


class ReplyInterviewRequest(BaseModel):
    session_id: str
    user_message: str


class ArchitectConfig(BaseModel):
    chapter_count: int = 4
    min_sections_per_chapter: int = 2
    max_sections_per_chapter: int = 4
    questions_per_section: int = 2


class ArchitectGenerateRequest(BaseModel):
    user_id: str
    course_id: str
    course_type: Optional[str] = None
    course_title: Optional[str] = None
    course_summary: Optional[str] = None
    key_topics: List[str] = Field(default_factory=list)
    rag_summary: Optional[RagSummary] = None
    interview_session_id: Optional[str] = None
    interview_result: Optional[Dict[str, Any]] = None
    architect_config: ArchitectConfig = Field(default_factory=ArchitectConfig)


class ProfilerAnalyzeRequest(BaseModel):
    user_id: str
    course_id: Optional[str] = None
    chapter_id: Optional[str] = None
    chapter_title: Optional[str] = None
    section_id: Optional[str] = None
    section_title: Optional[str] = None
    interaction_type: str = "tutor_dialogue"
    tutor_style: Optional[str] = None
    question_context: str = ""
    user_action: str = ""
    user_message: str = ""
    tutor_reply: str = ""
    user_feedback: str = ""
    messages: List[ChatMessage] = Field(default_factory=list)
    thinking_script_snapshot: Optional[Dict[str, Any]] = None
    learner_profile_snapshot: Optional[Dict[str, Any]] = None


class ClerkGenerateNoteRequest(BaseModel):
    user_id: str
    course_id: str
    chapter_id: Optional[str] = None
    chapter_title: Optional[str] = None
    section_id: Optional[str] = None
    section_title: Optional[str] = None
    note_title: Optional[str] = None
    focus_questions: List[str] = Field(default_factory=list)
    messages: List[ChatMessage] = Field(default_factory=list)
    user_takeaways: str = ""
    additional_context: str = ""
    auto_save: bool = False
    include_mindmap: bool = True


class ProgressUpdateRequest(BaseModel):
    user_id: str
    course_id: str
    current_chapter_id: Optional[str] = None
    current_chapter_title: Optional[str] = None
    current_section_id: Optional[str] = None
    current_section_title: Optional[str] = None
    completed_chapter_ids: List[str] = Field(default_factory=list)
    completed_section_ids: List[str] = Field(default_factory=list)
    event_type: str = "progress_update"
    progress_meta: Dict[str, Any] = Field(default_factory=dict)


class ConciergeRequest(BaseModel):
    user_id: str
    message: str
    current_page: Optional[str] = None
    course_id: Optional[str] = None
    allow_frontend_actions: bool = True
    available_frontend_actions: List[str] = Field(default_factory=list)
    context: Dict[str, Any] = Field(default_factory=dict)

# 6. 辅助函数：构建带有“记忆”的 System Prompt
def get_system_prompt_with_memory(username: str, db: Session):
    # 查询用户信息
    user = db.query(User).filter(User.username == username).first()
    # 查询所有掌握度不佳的知识点 (比如分值 < 60)
    weak_points = db.query(KnowledgeMastery).filter(
        KnowledgeMastery.user_id == (user.id if user else None),
        KnowledgeMastery.mastery_score < 60
    ).all()
    
    memory_context = ""
    if user:
        memory_context += f"\n用户背景：{user.background}，学习目标：每天 {user.daily_goal_minutes} 分钟。"
    
    if weak_points:
        points_str = ", ".join([f"{p.point_name}({p.mastery_score}分, 易错点: {p.error_summary})" for p in weak_points])
        memory_context += f"\n注：以下知识点用户掌握较弱，请优先关注或在对话中复习：{points_str}"

    return f"你是一位资深的编程导师，说话幽默风趣。{memory_context}"


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
    missing = []
    for slot in INTERVIEW_REQUIRED_SLOTS:
        if slot_state.get(slot, {}).get("status") != "filled":
            missing.append(slot)
    return missing


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


def merge_slot_state(
    current_state: Dict[str, Dict[str, Any]],
    updates: Optional[Dict[str, Any]]
):
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


def pick_next_slot(slot_state: Dict[str, Dict[str, Any]], llm_slot: Optional[str] = None):
    missing_slots = get_missing_slots(slot_state)
    if llm_slot in missing_slots:
        return llm_slot
    return missing_slots[0] if missing_slots else None


def build_question_for_slot(
    slot: Optional[str],
    context: Dict[str, Any],
    slot_state: Optional[Dict[str, Dict[str, Any]]] = None,
    include_intro: bool = False
):
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


def parse_json_response(content: str):
    text = (content or "").strip()
    if text.startswith("```json"):
        text = text.replace("```json", "").replace("```", "").strip()
    elif text.startswith("```"):
        text = text.replace("```", "").strip()
    return json.loads(text)


def get_interview_messages(db: Session, session_id: str):
    return db.query(InterviewMessage).filter(
        InterviewMessage.session_id == session_id
    ).order_by(InterviewMessage.created_at.asc(), InterviewMessage.id.asc()).all()


def build_interview_trace(messages: List[InterviewMessage]):
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


def ensure_list(value: Any):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        normalized = value.replace("，", ",").replace("、", ",")
        return [item.strip() for item in normalized.split(",") if item.strip()]
    return []


def infer_user_level(foundation_text: Optional[str]):
    text = (foundation_text or "").lower()
    if any(token in text for token in ["零基础", "没学过", "没有学过", "不会", "只知道", "beginner"]):
        return "beginner"
    if any(token in text for token in ["做过项目", "比较熟", "深入", "advanced"]):
        return "advanced"
    if any(token in text for token in ["了解一点", "接触过", "学过一些", "intermediate"]):
        return "intermediate"
    return "unknown"


def build_local_interview_summary(
    context: Dict[str, Any],
    slot_state: Dict[str, Dict[str, Any]],
    messages: List[InterviewMessage]
):
    foundation = slot_state.get("foundation", {}).get("value")
    goal = slot_state.get("goal", {}).get("value")
    pain_point = slot_state.get("pain_point", {}).get("value")
    preference = slot_state.get("preference", {}).get("value")
    course_title = context.get("course_title") or context.get("course_id") or "当前课程"

    return {
        "user_level": infer_user_level(foundation),
        "confidence": round(0.45 + count_filled_slots(slot_state) * 0.12, 2),
        "learning_goal": goal or "待进一步确认",
        "deadline": None,
        "preferred_style": ensure_list(preference),
        "pain_points": ensure_list(pain_point),
        "known_topics": [],
        "unknown_topics": [],
        "motivation": goal or "希望完成当前课程学习",
        "recommended_start_point": ensure_list(pain_point)[0] if ensure_list(pain_point) else course_title,
        "raw_slot_state": slot_state,
        "message_count": len(messages),
    }


def build_completion_payload(
    context: Dict[str, Any],
    slot_state: Dict[str, Dict[str, Any]],
    messages: List[InterviewMessage],
    termination_reason: str,
    llm_summary: Optional[Dict[str, Any]] = None
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
    messages: List[InterviewMessage],
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

    输出必须是合法 JSON，格式如下：
    {
      "slot_updates": {
        "foundation": {"status": "missing|filled", "value": "string or null", "evidence": "string"},
        "goal": {"status": "missing|filled", "value": "string or null", "evidence": "string"},
        "pain_point": {"status": "missing|filled", "value": "string or null", "evidence": "string"},
        "preference": {"status": "missing|filled", "value": "string or null", "evidence": "string"}
      },
      "should_finish": true,
      "termination_reason": "enough_information|user_requested_start|max_questions|needs_more_info",
      "next_question_slot": "foundation|goal|pain_point|preference|null",
      "assistant_reply": "一句话。如果未结束，这里必须是一个问题；如果结束，这里必须是简短收尾。",
      "interview_summary": {
        "user_level": "beginner|intermediate|advanced|unknown",
        "confidence": 0.0,
        "learning_goal": "string",
        "deadline": null,
        "preferred_style": ["string"],
        "pain_points": ["string"],
        "known_topics": ["string"],
        "unknown_topics": ["string"],
        "motivation": "string",
        "recommended_start_point": "string"
      }
    }

    如果还没结束，interview_summary 返回 null。
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


def normalize_course_plan(
    raw_plan: Dict[str, Any],
    context: Dict[str, Any],
    interview_payload: Dict[str, Any],
    interview_session_id: Optional[str] = None,
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
        sections_raw = chapter.get("sections") or []
        normalized_sections = []

        for section_index, section in enumerate(sections_raw, start=1):
            section = section or {}
            questions_raw = (
                section.get("practice_questions")
                or section.get("questions")
                or []
            )

            normalized_questions = []
            for question_index, question in enumerate(questions_raw, start=1):
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

                normalized_questions.append(normalized_question)

            normalized_sections.append({
                "id": section.get("id") or f"section_{chapter_index}_{section_index}",
                "title": str(section.get("title") or f"{chapter_index}.{section_index} 未命名小节").strip(),
                "objective": str(section.get("objective") or section.get("learning_objective") or "").strip(),
                "key_points": ensure_list(section.get("key_points")),
                "practice_questions": normalized_questions,
            })

        normalized_chapters.append({
            "id": chapter.get("id") or f"chapter_{chapter_index}",
            "title": str(chapter.get("title") or chapter.get("chapter_title") or f"第{chapter_index}章").strip(),
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


def normalize_course_section_node(section: Any, chapter_index: int, section_index: int):
    if isinstance(section, dict):
        return {
            "id": section.get("id") or f"section_{chapter_index}_{section_index}",
            "title": str(section.get("title") or section.get("section_title") or f"{chapter_index}.{section_index} 未命名小节").strip(),
            "objective": str(section.get("objective") or section.get("learning_objective") or "").strip(),
            "key_points": ensure_list(section.get("key_points")),
            "practice_questions": section.get("practice_questions") or section.get("questions") or [],
        }

    return {
        "id": f"section_{chapter_index}_{section_index}",
        "title": str(section).strip() or f"{chapter_index}.{section_index} 未命名小节",
        "objective": "",
        "key_points": [],
        "practice_questions": [],
    }


def normalize_course_chapter_node(chapter: Any, chapter_index: int):
    if not isinstance(chapter, dict):
        chapter = {}

    sections_raw = chapter.get("sections") or []
    sections = [
        normalize_course_section_node(section, chapter_index, section_index)
        for section_index, section in enumerate(sections_raw, start=1)
    ]

    return {
        "id": chapter.get("id") or f"chapter_{chapter_index}",
        "title": str(chapter.get("title") or chapter.get("chapter_title") or f"第{chapter_index}章").strip(),
        "description": str(chapter.get("description") or "").strip(),
        "learning_goals": ensure_list(chapter.get("learning_goals")),
        "sections": sections,
    }


def normalize_full_course_plan(course_plan: Any):
    if not isinstance(course_plan, dict):
        return None

    chapters_raw = course_plan.get("chapters") or []
    normalized_chapters = [
        normalize_course_chapter_node(chapter, chapter_index)
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


def resolve_tutor_section_context(course_plan: Optional[Dict[str, Any]], request: TutorRequest):
    if not course_plan:
        return None

    normalized_plan = normalize_full_course_plan(course_plan)
    if not normalized_plan:
        return None

    selected_chapter = None
    selected_section = None

    for chapter in normalized_plan["chapters"]:
        chapter_match = match_course_node(request.chapter_id, chapter.get("id")) or match_course_node(
            request.chapter_title, chapter.get("title")
        )

        for section in chapter.get("sections", []):
            section_match = match_course_node(request.section_id, section.get("id")) or match_course_node(
                request.section_title, section.get("title")
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
            UserSyllabus.course_id == request.course_id
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
            )
        })

    for msg in request.messages:
        messages.append({"role": msg.role, "content": msg.content})

    return messages


def prepare_tutor_runtime(request: TutorRequest, db: Session):
    tutor_context = build_tutor_context(request, db)
    messages = build_tutor_messages(request, tutor_context)
    return tutor_context, messages


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


def merge_unique_items(existing: List[str], new_items: List[str], limit: int = 12):
    merged = []
    seen = set()

    for item in list(existing) + list(new_items):
        normalized = str(item).strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            merged.append(normalized)
        if len(merged) >= limit:
            break

    return merged


def normalize_cognitive_profile(
    raw_profile: Optional[Dict[str, Any]],
    learner_profile: Optional[Dict[str, Any]] = None,
):
    thinker = normalize_thinking_script(raw_profile, learner_profile)
    raw_profile = raw_profile if isinstance(raw_profile, dict) else {}

    normalized = {
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

    return normalized


def resolve_profiler_context(request: ProfilerAnalyzeRequest, db: Session):
    course_plan = None
    section_context = None

    if request.user_id and request.course_id:
        syllabus_record = db.query(UserSyllabus).filter(
            UserSyllabus.user_id == request.user_id,
            UserSyllabus.course_id == request.course_id
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
    merged["updated_at"] = datetime.utcnow().isoformat()

    return merged


def resolve_clerk_context(request: ClerkGenerateNoteRequest, db: Session):
    syllabus_record = db.query(UserSyllabus).filter(
        UserSyllabus.user_id == request.user_id,
        UserSyllabus.course_id == request.course_id
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
        CognitiveProfileObservation.id.desc()
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
        UserSyllabus.course_id == course_id
    ).first()


def get_or_create_progress_record(request: ProgressUpdateRequest, db: Session):
    record = db.query(UserLearningProgress).filter(
        UserLearningProgress.user_id == request.user_id,
        UserLearningProgress.course_id == request.course_id
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

# 7. 编写测试对话接口
@app.post("/api/agent/chat")
async def chat_with_agent(request: ChatRequest, db: Session = Depends(get_db)):
    try:
        system_content = get_system_prompt_with_memory(request.username, db)
        
        # 🚨 核心逻辑：组装历史消息
        messages = [{"role": "system", "content": system_content}]
        for msg in request.messages:
            messages.append({"role": msg.role, "content": msg.content})

        # 调用千问大模型 (这里以 qwen-plus 为例，你可以根据需要换成 qwen-max 等)
        response = client.chat.completions.create(
            model="qwen-plus", 
            messages=messages,
        )

        # 提取并返回 AI 的回答
        ai_reply = response.choices[0].message.content
        return {"status": "success", "reply": ai_reply}

    except Exception as e:
        # 错误处理
        raise HTTPException(status_code=500, detail=str(e))

# 8. 编写流式对话接口
@app.post("/api/agent/chat/stream")
async def chat_with_agent_stream(request: ChatRequest, db: Session = Depends(get_db)):
    async def generate_response():
        try:
            # 判断当前是“采访模式”还是“做题/辅导模式”
            # 如果是空字典 {} 或者 null，说明在采访
            if not request.current_question:
                system_prompt = """
                你是一个专业的 AI 课程规划师。你的任务是通过自然的对话，收集用户的学习情报。
                
                【🎯 你的核心情报收集清单】：
                1. 用户的当前基础（零基础/有经验/卡在某个瓶颈）。
                2. 核心学习目标（找工作/考试/做项目/纯兴趣）。
                3. 每日或每周可用的学习时间。
                
                【💡 你的聊天策略】：
                - 像真人一样聊天，一次只问一个最需要补充的情报。
                - 每次回复字数控制在 50 字以内。
                
                【🚨 极其重要的终止条件（暗号指令）- 违者断电】：
                1. 每次回复前，必须在心里核对 3 项情报是否【全部】收集完毕。
                2. 如果你还在向用户提问（比如问时间、问目标），【绝对、绝对不能】输出暗号！
                3. 只有当 3 项情报彻底收集完毕，且你不需要再问任何问题时，请在最后一句说“太棒了，请点击下方按钮生成大纲！”，并且在整段话的最末尾，加上这个纯英文字符串：###DONE###
                
                错误示范（还在提问就加暗号）："你每天能学多久？###DONE###" ❌
                正确示范（情报收齐闭环）："我已经完全掌握你的情况了！请点击下方按钮！###DONE###" ✅
                """
            else:
                # ==========================================
                # 做题阶段：正常加载导师人设和记忆
                # ==========================================
                base_memory = get_system_prompt_with_memory(request.username, db)
                current_q_title = request.current_question.get('title', '未知')
                system_prompt = f"""
                {base_memory}
                你现在的具体身份是：AI编程私教。性格设定为：{request.persona}。
                用户当前正在挑战的题目是：【{current_q_title}】
                
                【🚨 极其重要的最高行为准则 🚨】
                在回复前，请务必先判断用户的最新发言属于以下哪种情况，并严格执行对应策略：
                
                情况 A（求助原题）：用户在询问这道题怎么做、请求代码提示、或者反馈代码报错。
                -> 策略：严格遵守【启发式教学】！循序渐进地给出思考方向，绝对禁止直接给出完整答案或代码。
                
                情况 B（知识延伸/偏题）：用户问了与当前题目原意无关的扩展知识（例如：“那 Java 怎么写？”、“什么是二叉树？”、“这块语法还有别的用法吗？”）。
                -> 策略：【立即放下原题执念】！停止催促做题，直接、详细、充满热情地解答用户的新疑问！绝对不允许在未解决新疑问前强行拉回到原题！
                
                请始终使用 Markdown 格式输出。
                """
            
            # 3. 组装完整记忆链（系统指令 + 历史对话）
            messages = [{"role": "system", "content": system_prompt}]
            for msg in request.messages:
                messages.append({"role": msg.role, "content": msg.content})
            
            # 使用流式返回
            response = client.chat.completions.create(
                model="qwen-plus", 
                messages=messages,
                stream=True 
            )
            
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content is not None:
                    # 提取每个字的片段
                    content = chunk.choices[0].delta.content
                    # 按照 SSE (Server-Sent Events) 格式返回数据
                    yield f"data: {content}\n\n"
                    # 稍微加一点延迟，让打字效果更平滑
                    await asyncio.sleep(0.02) 
        except Exception as e:
            yield f"data: Error: {str(e)}\n\n"
                
    # 返回流式响应
    return StreamingResponse(generate_response(), media_type="text/event-stream")

# 9. 新增：更新用户信息接口
@app.post("/api/user/profile")
async def update_user_profile(request: UserProfileRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == request.username).first()
    if not user:
        user = User(username=request.username)
        db.add(user)
    
    user.background = request.background
    user.daily_goal_minutes = request.daily_goal_minutes
    db.commit()
    return {"status": "success", "message": "用户信息已更新"}

# 10. 新增：更新掌握度接口
@app.post("/api/knowledge/update")
async def update_knowledge_mastery(request: MasteryUpdateRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == request.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    record = db.query(KnowledgeMastery).filter(
        KnowledgeMastery.user_id == user.id,
        KnowledgeMastery.point_name == request.point_name
    ).first()
    
    if not record:
        record = KnowledgeMastery(user_id=user.id, point_name=request.point_name)
        db.add(record)
    
    record.mastery_score = request.mastery_score
    record.error_summary = request.error_summary
    db.commit()
    return {"status": "success", "message": f"{request.point_name} 的掌握度已更新"}


@app.post("/api/interview/start")
async def start_interview(request: StartInterviewRequest, db: Session = Depends(get_db)):
    try:
        context = build_interview_context(request)
        slot_state = build_default_slot_state()
        session_id = f"iv_{uuid.uuid4().hex[:12]}"
        opening_question = build_question_for_slot(
            "foundation",
            context,
            slot_state=slot_state,
            include_intro=True,
        )

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
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"启动访谈失败: {str(e)}")


@app.post("/api/interview/reply")
async def reply_interview(request: ReplyInterviewRequest, db: Session = Depends(get_db)):
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

    try:
        db.add(InterviewMessage(session_id=session.id, role="user", content=request.user_message))
        db.flush()

        slot_state = session.slot_state or build_default_slot_state()
        context = session.context_data or {}
        messages = get_interview_messages(db, session.id)

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
            llm_result = {}

        slot_state = merge_slot_state(slot_state, llm_result.get("slot_updates"))
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
        assistant_reply = llm_result.get("assistant_reply") or build_question_for_slot(next_slot, context, slot_state)
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
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"处理访谈回复失败: {str(e)}")


@app.get("/api/interview/{session_id}")
async def get_interview_session_detail(session_id: str, db: Session = Depends(get_db)):
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


@app.post("/api/architect/generate-course-plan")
async def generate_course_plan(request: ArchitectGenerateRequest, db: Session = Depends(get_db)):
    context, interview_payload, session = resolve_architect_inputs(request, db)

    system_prompt = """
    你是智能学习平台的“课程架构师 Agent”。

    你的任务：
    1. 读取课程上下文和访谈结果，把课程结构化为适合前端渲染的学习蓝图。
    2. 必须根据用户基础、目标、痛点和偏好来调整难度和顺序。
    3. 对标准课，优先围绕 key_topics 组织内容。
    4. 对自定义课，优先围绕 rag_summary 中的资料主题和关键词组织内容，不要脱离资料。
    5. 每个章节都要给出学习目标；每个小节都要给出学习目标和练习题。

    输出必须是合法 JSON 对象，不要包含 Markdown。

    JSON 格式：
    {
      "title": "课程标题",
      "description": "针对这个用户的定制化课程说明",
      "course_objectives": ["目标1", "目标2"],
      "recommended_start_point": "建议起点",
      "chapters": [
        {
          "id": "chapter_1",
          "title": "第一章：xxx",
          "description": "为什么先学这一章",
          "learning_goals": ["目标1", "目标2"],
          "sections": [
            {
              "id": "section_1_1",
              "title": "1.1 xxx",
              "objective": "学完这节要做到什么",
              "key_points": ["知识点1", "知识点2"],
              "practice_questions": [
                {
                  "id": "q_1_1_1",
                  "type": "choice",
                  "question": "题目文本",
                  "options": [
                    {"label": "A", "text": "选项A"},
                    {"label": "B", "text": "选项B"}
                  ],
                  "answer": "A",
                  "explanation": "为什么",
                  "hint": "提示"
                },
                {
                  "id": "q_1_1_2",
                  "type": "fill",
                  "question": "填空题文本",
                  "answer": "答案",
                  "explanation": "解释",
                  "hint": "提示"
                }
              ]
            }
          ]
        }
      ]
    }

    约束：
    - 章节数尽量贴近请求里的 chapter_count。
    - 每章小节数控制在 min_sections_per_chapter 到 max_sections_per_chapter 之间。
    - 每节练习题数量贴近 questions_per_section。
    - 题目难度要匹配用户水平，不能明显超纲。
    - 输出内容务必简洁、具体、可执行。
    """

    user_prompt = json.dumps(
        {
            "course_context": context,
            "interview_result": interview_payload,
            "generation_rules": request.architect_config.model_dump(),
        },
        ensure_ascii=False,
    )

    try:
        response = client.chat.completions.create(
            model="qwen-plus",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )

        raw_plan = parse_json_response(response.choices[0].message.content)
        normalized_plan = normalize_course_plan(
            raw_plan=raw_plan,
            context=context,
            interview_payload=interview_payload,
            interview_session_id=request.interview_session_id,
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
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"生成课程蓝图失败: {str(e)}")

# 11. 改造生成大纲的接口：生成完毕后存入数据库
@app.post("/api/onboarding/generate-syllabus")
async def generate_syllabus(request: SyllabusRequest, db: Session = Depends(get_db)):
    # 核心心法：强制大模型输出 JSON 格式的 System Prompt
    system_prompt = """
    你是一个资深的编程教研专家。请根据用户的课程意向和个人背景，为他定制一份专属的学习大纲。
    你必须且只能返回一个合法的 JSON 数据，不要有任何额外的 Markdown 标记（如 ```json）或解释性文字。
    
    JSON 数据结构必须如下：
    {
      "title": "课程主标题",
      "description": "一段鼓励用户的定制化寄语",
      "chapters": [
        {
          "chapter_title": "第一章：基础入门",
          "sections": ["1. 变量与数据类型", "2. 运算符"]
        }
      ]
    }
    """
    
    user_prompt = f"我要学：{request.course_name}。我的情况是：{request.user_background}。"

    try:
        response = client.chat.completions.create(
            model="qwen-plus",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            # 开启 JSON 模式约束
            response_format={"type": "json_object"} 
        )
        
        ai_reply = response.choices[0].message.content
        
        # 将大模型返回的字符串解析为真正的 Python 字典，验证其合法性
        syllabus_data = json.loads(ai_reply)

        # 【数据库持久化操作】
        existing_syllabus = db.query(UserSyllabus).filter(
            UserSyllabus.user_id == request.user_id,
            UserSyllabus.course_id == request.course_id
        ).first()

        if existing_syllabus:
            # 如果已有大纲，进行更新
            existing_syllabus.syllabus_data = syllabus_data
        else:
            # 如果是新课程，创建新记录
            new_syllabus = UserSyllabus(
                user_id=request.user_id,
                course_id=request.course_id,
                syllabus_data=syllabus_data
            )
            db.add(new_syllabus)
        
        db.commit()
        return {"status": "success", "data": syllabus_data, "message": "大纲已成功生成并持久化到数据库！"}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"生成或保存大纲失败: {str(e)}")

# 12. 新增：获取定制大纲的接口
@app.get("/api/curriculum/{user_id}/{course_id}")
async def get_curriculum(user_id: str, course_id: str, db: Session = Depends(get_db)):
    # 去数据库里查询匹配的记录
    syllabus_record = db.query(UserSyllabus).filter(
        UserSyllabus.user_id == user_id,
        UserSyllabus.course_id == course_id
    ).first()

    if not syllabus_record:
        # 如果没找到，返回 404 错误
        raise HTTPException(status_code=404, detail="未找到该课程的定制大纲，请先进行采访")

    # 如果找到了，直接返回存好的 JSON 数据
    return {"status": "success", "data": syllabus_record.syllabus_data}

# 13. Agent 3：陪伴导师（支持课程上下文 + 思维方式脚本）
@app.post("/api/tutor/respond")
async def tutor_chat(request: TutorRequest, db: Session = Depends(get_db)):
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
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"陪伴导师回复失败: {str(e)}")


@app.post("/api/study/tutor-chat/stream")
async def tutor_chat_stream(request: TutorRequest, db: Session = Depends(get_db)):
    tutor_context, messages = prepare_tutor_runtime(request, db)

    async def generate_response():
        try:
            response = client.chat.completions.create(
                model="qwen-plus",
                messages=messages,
                stream=True
            )
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    yield f"data: {content}\n\n"
                    await asyncio.sleep(0.01)
        except Exception as e:
            yield f"data: [Error] 导师掉线了: {str(e)}\n\n"

    return StreamingResponse(generate_response(), media_type="text/event-stream")


@app.post("/api/profiler/analyze-interaction")
async def analyze_learning_interaction(request: ProfilerAnalyzeRequest, db: Session = Depends(get_db)):
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
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"思维画像分析失败: {str(e)}")


@app.get("/api/profiler/profile/{user_id}")
async def get_cognitive_profile(user_id: str, db: Session = Depends(get_db)):
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
        }
    }


@app.post("/api/progress/update")
async def update_learning_progress(request: ProgressUpdateRequest, db: Session = Depends(get_db)):
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
        record.last_activity_at = datetime.utcnow()

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
            }
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"更新学习进度失败: {str(e)}")


@app.get("/api/progress/{user_id}")
async def get_learning_progress(user_id: str, course_id: Optional[str] = None, db: Session = Depends(get_db)):
    if course_id:
        record = db.query(UserLearningProgress).filter(
            UserLearningProgress.user_id == user_id,
            UserLearningProgress.course_id == course_id
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
            }
        }

    return {
        "status": "success",
        "data": build_user_progress_overview(user_id, db),
    }


@app.post("/api/concierge/respond")
async def concierge_respond(request: ConciergeRequest, db: Session = Depends(get_db)):
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
                }
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"全局助手响应失败: {str(e)}")


@app.post("/api/clerk/generate-note")
async def generate_clerk_note(request: ClerkGenerateNoteRequest, db: Session = Depends(get_db)):
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
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"生成智能笔记失败: {str(e)}")
# 14. 新增：生成复盘笔记的接口
@app.post("/api/notes/generate")
async def generate_review_note(request: NoteRequest):
    # 🚨 核心升级：增加 Mermaid 思维导图生成的 System Prompt
    system_prompt = """
    你是一位资深的编程教研专家。你需要根据用户的学习进度和薄弱点，为他生成一份精美的【专属复盘笔记】。
    
    输出要求：
    1. 必须使用 Markdown 格式（使用 ### 标题、- 列表、**加粗**等）。
    2. 结构必须包含以下三部分：
       - 🌟 核心知识点回顾（根据用户学过的内容提炼干货）
       - ⚠️ 易错点避坑指南（针对用户的薄弱点给出具体的防错建议）
       - 🚀 下一步学习建议（一两句话鼓励）
    3. 🧠 终极要求：在整篇笔记的最底部，你必须使用 mermaid 语法生成一个 mindmap（思维导图），用来总结这篇笔记的核心结构。
    
    语法规则（极其重要，违反将导致渲染失败）：
    1. 必须以 mindmap 开头。
    2. 每个节点文字必须用双引号包裹，例如： "root((我的笔记))" 或 "分支(\"特殊字符\")"。
    3. 严禁在节点文字内使用未转义的双引号。
    4. 必须严格遵守缩进层级。
    
    正确示例：
    ```mermaid
    mindmap
      root(("Python 基础"))
        "变量"
          "命名规则"
          "数据类型"
        "函数"
          "print() 函数"
          "input() 函数"
    ```
    语气要专业、清晰，直接输出 Markdown 正文，不要包含任何多余的解释。
    """
    
    user_prompt = f"课程：{request.course_name}\n已学内容：{request.learned_topics}\n薄弱点：{request.weak_points}"

    try:
        response = client.chat.completions.create(
            model="qwen-plus",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        
        note_content = response.choices[0].message.content
        return {"status": "success", "data": {"title": f"{request.course_name} 专属复盘笔记", "content": note_content}}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成笔记失败: {str(e)}")

# 15. 新增：提炼脑图的接口 (供手动笔记使用)
@app.post("/api/notes/extract-mindmap")
async def extract_mindmap(request: MindmapOnlyRequest):
    system_prompt = """
    你是一个逻辑精炼专家。请将用户提供的笔记内容提炼成一个 Mermaid 思维导图。
    
    规则：
    1. 必须以 mindmap 开头。
    2. 必须且只能输出 ```mermaid ... ``` 格式的代码块。
    3. 每个节点必须用双引号包裹，如 "节点名称"。
    4. 不要包含任何开场白、解释或总结，只给代码。
    5. 层级不要太深（建议 3 层以内），确保排版清晰。
    """
    
    try:
        response = client.chat.completions.create(
            model="qwen-plus",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请为以下笔记提炼思维导图：\n\n{request.content}"}
            ]
        )
        
        mermaid_code = response.choices[0].message.content
        return {"status": "success", "data": mermaid_code}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 16. 新增：动态生成测试题的接口
@app.post("/api/study/generate-questions")
async def generate_questions(request: QuestionRequest):
    system_prompt = """
    你是一个专业的编程课程教研员。请根据用户提供的课程和章节信息，生成 3 道测试题。
    测试题必须包含选择题和填空题（至少各一道）。
    
    【极其重要的输出格式要求】
    你必须且只能返回一个合法的 JSON 数组，不要包含任何 Markdown 标记，不要用 ```json 包裹，直接输出纯净的 JSON 字符串。
    
    JSON 格式示例：
    [
      {
        "id": "q1",
        "type": "choice",
        "question": "Python 是一种什么语言？",
        "options": [
          {"label": "A", "text": "编译型"},
          {"label": "B", "text": "解释型"},
          {"label": "C", "text": "标记型"},
          {"label": "D", "text": "汇编型"}
        ],
        "answer": "B",
        "explanation": "Python 是一种解释型语言，代码逐行翻译执行。",
        "hint": "运行代码时需不需要先编译？"
      },
      {
        "id": "q2",
        "type": "fill",
        "question": "在命令行查看 Python 版本的命令是 ______",
        "answer": "python --version",
        "explanation": "使用 python --version 查看版本。",
        "hint": "前面是 python，后面带 version"
      }
    ]
    """
    
    user_prompt = f"请为课程ID：{request.course_id}，章节：{request.section_title} 生成 3 道题目。"
    
    try:
        response = client.chat.completions.create(
            model="qwen-plus",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        
        # 移除可能存在的 Markdown 标记
        content = response.choices[0].message.content
        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "").strip()
        elif content.startswith("```"):
            content = content.replace("```", "").strip()
            
        questions = json.loads(content)
        return {"status": "success", "data": questions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成题目失败: {str(e)}")

@app.get("/")
async def root():
    return {"message": "AI 后端服务已启动！"}

# 新增：获取用户生成的自定义课程列表
@app.get("/api/user/custom-courses/{user_id}")
async def get_user_custom_courses(user_id: str, db: Session = Depends(get_db)):
    # 去数据库里查询该用户所有以 "custom_" 开头的课程记录
    courses = db.query(UserSyllabus).filter(
        UserSyllabus.user_id == user_id,
        UserSyllabus.course_id.like("custom_%")
    ).all()
    
    # 整理数据返回给前端
    course_list = []
    for c in courses:
        title = "专属定制课程"
        # 尝试从 JSON 数据中读取 course_title，如果之前存了的话
        if isinstance(c.syllabus_data, dict):
            if "course_title" in c.syllabus_data:
                title = c.syllabus_data["course_title"]
            elif "title" in c.syllabus_data:
                title = c.syllabus_data["title"]

        course_list.append({
            "course_id": c.course_id,
            "title": title,
        })
        
    return {"status": "success", "data": course_list}

# 新增：删除自定义课程的接口
@app.delete("/api/user/custom-courses/{course_id}")
async def delete_custom_course(course_id: str, db: Session = Depends(get_db)):
    # 去数据库里找到这门课
    course = db.query(UserSyllabus).filter(UserSyllabus.course_id == course_id).first()
    
    if not course:
        raise HTTPException(status_code=404, detail="未找到该课程")
        
    # 执行删除并提交
    db.delete(course)
    db.commit()
    
    return {"status": "success", "message": "课程已永久删除"}

# -------------------------------------------
# 📝 笔记系统核心接口
# -------------------------------------------

# 1. 保存新笔记
@app.post("/api/notes/save")
async def save_user_note(request: CreateNoteRequest, db: Session = Depends(get_db)):
    try:
        new_note = UserNote(
            user_id=request.user_id,
            course_id=request.course_id,
            title=request.title,
            content=request.content
        )
        db.add(new_note)
        db.commit()
        return {"status": "success", "message": "笔记已成功保存入库！"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"保存笔记失败: {str(e)}")

# 2. 获取用户的所有笔记（用于渲染那个“笔记”页面）
@app.get("/api/notes/list/{user_id}")
async def get_user_notes_list(user_id: str, db: Session = Depends(get_db)):
    notes = db.query(UserNote).filter(
        UserNote.user_id == user_id
    ).order_by(UserNote.created_at.desc()).all()
    
    # 整理并返回数据
    note_list = []
    for n in notes:
        note_list.append({
            "id": n.id,
            "course_id": n.course_id,
            "title": n.title,
            "content": n.content,
            "created_at": n.created_at.strftime("%Y-%m-%d %H:%M")
        })
        
    return {"status": "success", "data": note_list}



# 17. 新增：支持 PDF 上传并生成自定义大纲的接口
@app.post("/api/onboarding/generate-custom-syllabus")
async def generate_custom_syllabus(
    file: UploadFile = File(...),
    course_title: str = Form(...),
    user_profile: str = Form(...), # 前端传过来的聊天记录字符串或 JSON
    db: Session = Depends(get_db)  # 🚨 新增：接上数据库水管
):
    print(f"🚀 收到自定义课程请求: {course_title}, 文件名: {file.filename}")
    
    # ==========================================
    # 步骤 1：启动“碎纸机”，在内存中读取 PDF 文字
    # ==========================================
    try:
        pdf_bytes = await file.read()
        extracted_text = ""
        
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            # ⚠️ 架构师的安全锁：为了防止几百页的PDF直接把大模型的Token撑爆，
            # 且生成大纲通常只需要看目录和前几页，我们暂时只读取前 10 页的内容。
            for i, page in enumerate(pdf.pages):
                if i >= 10: 
                    extracted_text += "\n...[内容过长，已截断]..."
                    break
                text = page.extract_text()
                if text:
                    extracted_text += text + "\n"
                    
    except Exception as e:
        print(f"解析 PDF 失败: {str(e)}")
        raise HTTPException(status_code=400, detail=f"解析 PDF 失败: {str(e)}")

    # ==========================================
    # 步骤 2：解析用户画像
    # ==========================================
    try:
        profile_data = json.loads(user_profile)
    except:
        profile_data = user_profile

    # ==========================================
    # 步骤 3：拼装“超级 Prompt”，召唤大模型
    # ==========================================
    prompt = f"""
    你是一位顶级的课程规划师。用户想要学习的自定义课程名称是：【{course_title}】。
    
    以下是用户上传的专属复习资料/教材的核心内容提取：
    ---开始---
    {extracted_text[:6000]}  # 限制最多取6000字，既保证内容丰富，又不超 Token 限制
    ---结束---

    以下是该用户的学习情况（采访画像）：
    {profile_data}

    🎯 你的任务：
    请严格根据以上【用户上传的复习资料内容】和【用户的学习情况】，为他量身定制一个包含“章”和“节”的详细学习大纲。
    要求：
    1. 生成 4 到 5 个核心章节（章）。
    2. 每个章节下，必须提炼出 2 到 4 个具体的核心知识点作为“节”。
    3. 内容必须紧扣他上传的资料，绝不瞎编乱造！
    4. 必须严格按照以下 JSON 数组格式返回，直接输出纯 JSON：
    [
      {{
        "title": "第一章：xxx", 
        "description": "xxx",
        "sections": [
            {{"title": "1.1 什么是xxx"}},
            {{"title": "1.2 xxx的核心原理"}}
        ]
      }},
      {{
        "title": "第二章：xxx", 
        "description": "xxx",
        "sections": [
            {{"title": "2.1 xxx的分类"}},
            {{"title": "2.2 xxx的实践"}}
        ]
      }}
    ]
    """

    try:
        # 调用通义千问生成大纲
        response = client.chat.completions.create(
            model="qwen-plus",
            messages=[{"role": "user", "content": prompt}]
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # 兼容处理：万一大模型不听话加了 ```json 标签，我们帮它去掉
        if result_text.startswith("```json"):
            result_text = result_text.replace("```json", "").replace("```", "").strip()
        elif result_text.startswith("```"):
            result_text = result_text.replace("```", "").strip()

        # 将字符串转为真实的 JSON 对象
        syllabus = json.loads(result_text)

        # ==========================================
        # 🚨 步骤 4：持久化！存入数据库
        # ==========================================
        # 为这个自定义课程生成一个独一无二的 ID（比如: custom_8a2b9c）
        custom_course_id = f"custom_{uuid.uuid4().hex[:8]}"
        user_id = "user_123" # 暂时用固定测试用户，以后接了登录可以换成真实的

        new_syllabus = UserSyllabus(
            user_id=user_id,
            course_id=custom_course_id,
            syllabus_data=syllabus
        )
        db.add(new_syllabus)
        db.commit()

        # 返回时，不仅把大纲返回给前端，还要把生成的 course_id 也给它
        return {
            "status": "success", 
            "data": syllabus, 
            "course_id": custom_course_id, # 👈 前端需要拿着个ID
            "message": "自定义大纲已成功刻入数据库！"
        }
    except Exception as e:
        print("生成大纲失败或解析 JSON 失败:", str(e))
        db.rollback() # 报错时回滚数据库
        return {"status": "error", "message": f"生成大纲失败: {str(e)}"}
