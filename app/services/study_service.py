import json

from fastapi import HTTPException

from app.core.config import client
from app.schemas.study import QuestionRequest


def generate_questions_flow(request: QuestionRequest):
    system_prompt = """
    你是一个专业的编程课程教研员。请根据用户提供的课程和章节信息，生成 3 道测试题。
    测试题必须包含选择题和填空题（至少各一道）。
    
    【极其重要的输出格式要求】
    你必须且只能返回一个合法的 JSON 数组，不要包含任何 Markdown 标记，不要用 ```json 包裹，直接输出纯净的 JSON 字符串。
    """

    user_prompt = f"请为课程ID：{request.course_id}，章节：{request.section_title} 生成 3 道题目。"

    try:
        response = client.chat.completions.create(
            model="qwen-plus",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        content = response.choices[0].message.content
        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "").strip()
        elif content.startswith("```"):
            content = content.replace("```", "").strip()

        questions = json.loads(content)
        return {"status": "success", "data": questions}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"生成题目失败: {str(exc)}")
