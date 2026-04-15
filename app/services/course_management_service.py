import json
import uuid
from io import BytesIO

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import client
from app.db.models import UserSyllabus
from app.schemas.syllabus import SyllabusRequest


def generate_syllabus_flow(request: SyllabusRequest, db: Session):
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
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )

        syllabus_data = json.loads(response.choices[0].message.content)

        existing_syllabus = db.query(UserSyllabus).filter(
            UserSyllabus.user_id == request.user_id,
            UserSyllabus.course_id == request.course_id,
        ).first()

        if existing_syllabus:
            existing_syllabus.syllabus_data = syllabus_data
        else:
            db.add(UserSyllabus(
                user_id=request.user_id,
                course_id=request.course_id,
                syllabus_data=syllabus_data,
            ))

        db.commit()
        return {"status": "success", "data": syllabus_data, "message": "大纲已成功生成并持久化到数据库！"}
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"生成或保存大纲失败: {str(exc)}")


def get_curriculum_flow(user_id: str, course_id: str, db: Session):
    syllabus_record = db.query(UserSyllabus).filter(
        UserSyllabus.user_id == user_id,
        UserSyllabus.course_id == course_id,
    ).first()

    if not syllabus_record:
        raise HTTPException(status_code=404, detail="未找到该课程的定制大纲，请先进行采访")

    return {"status": "success", "data": syllabus_record.syllabus_data}


def get_user_custom_courses_flow(user_id: str, db: Session):
    courses = db.query(UserSyllabus).filter(
        UserSyllabus.user_id == user_id,
        UserSyllabus.course_id.like("custom_%"),
    ).all()

    course_list = []
    for course in courses:
        title = "专属定制课程"
        if isinstance(course.syllabus_data, dict):
            if "course_title" in course.syllabus_data:
                title = course.syllabus_data["course_title"]
            elif "title" in course.syllabus_data:
                title = course.syllabus_data["title"]

        course_list.append({
            "course_id": course.course_id,
            "title": title,
        })

    return {"status": "success", "data": course_list}


def delete_custom_course_flow(course_id: str, db: Session):
    course = db.query(UserSyllabus).filter(UserSyllabus.course_id == course_id).first()

    if not course:
        raise HTTPException(status_code=404, detail="未找到该课程")

    db.delete(course)
    db.commit()
    return {"status": "success", "message": "课程已永久删除"}


async def generate_custom_syllabus_flow(
    file: UploadFile,
    course_title: str,
    user_profile: str,
    db: Session,
):
    print(f"🚀 收到自定义课程请求: {course_title}, 文件名: {file.filename}")

    try:
        import pdfplumber

        pdf_bytes = await file.read()
        extracted_text = ""

        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for index, page in enumerate(pdf.pages):
                if index >= 10:
                    extracted_text += "\n...[内容过长，已截断]..."
                    break
                text = page.extract_text()
                if text:
                    extracted_text += text + "\n"
    except Exception as exc:
        print(f"解析 PDF 失败: {str(exc)}")
        raise HTTPException(status_code=400, detail=f"解析 PDF 失败: {str(exc)}")

    try:
        profile_data = json.loads(user_profile)
    except Exception:
        profile_data = user_profile

    prompt = f"""
    你是一位顶级的课程规划师。用户想要学习的自定义课程名称是：【{course_title}】。
    
    以下是用户上传的专属复习资料/教材的核心内容提取：
    ---开始---
    {extracted_text[:6000]}
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
        response = client.chat.completions.create(
            model="qwen-plus",
            messages=[{"role": "user", "content": prompt}],
        )

        result_text = response.choices[0].message.content.strip()
        if result_text.startswith("```json"):
            result_text = result_text.replace("```json", "").replace("```", "").strip()
        elif result_text.startswith("```"):
            result_text = result_text.replace("```", "").strip()

        syllabus = json.loads(result_text)
        custom_course_id = f"custom_{uuid.uuid4().hex[:8]}"
        user_id = "user_123"

        db.add(UserSyllabus(
            user_id=user_id,
            course_id=custom_course_id,
            syllabus_data=syllabus,
        ))
        db.commit()

        return {
            "status": "success",
            "data": syllabus,
            "course_id": custom_course_id,
            "message": "自定义大纲已成功刻入数据库！",
        }
    except Exception as exc:
        print("生成大纲失败或解析 JSON 失败:", str(exc))
        db.rollback()
        return {"status": "error", "message": f"生成大纲失败: {str(exc)}"}
