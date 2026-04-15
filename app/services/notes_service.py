from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import client
from app.db.models import UserNote
from app.schemas.notes import CreateNoteRequest, MindmapOnlyRequest, NoteRequest


def generate_review_note_flow(request: NoteRequest):
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
    """

    user_prompt = f"课程：{request.course_name}\n已学内容：{request.learned_topics}\n薄弱点：{request.weak_points}"

    try:
        response = client.chat.completions.create(
            model="qwen-plus",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        note_content = response.choices[0].message.content
        return {"status": "success", "data": {"title": f"{request.course_name} 专属复盘笔记", "content": note_content}}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"生成笔记失败: {str(exc)}")


def extract_mindmap_flow(request: MindmapOnlyRequest):
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
                {"role": "user", "content": f"请为以下笔记提炼思维导图：\n\n{request.content}"},
            ],
        )

        return {"status": "success", "data": response.choices[0].message.content}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def save_user_note_flow(request: CreateNoteRequest, db: Session):
    try:
        new_note = UserNote(
            user_id=request.user_id,
            course_id=request.course_id,
            title=request.title,
            content=request.content,
        )
        db.add(new_note)
        db.commit()
        return {"status": "success", "message": "笔记已成功保存入库！"}
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"保存笔记失败: {str(exc)}")


def get_user_notes_list_flow(user_id: str, db: Session):
    notes = db.query(UserNote).filter(
        UserNote.user_id == user_id
    ).order_by(UserNote.created_at.desc()).all()

    note_list = []
    for note in notes:
        note_list.append({
            "id": note.id,
            "course_id": note.course_id,
            "title": note.title,
            "content": note.content,
            "created_at": note.created_at.strftime("%Y-%m-%d %H:%M"),
        })

    return {"status": "success", "data": note_list}
