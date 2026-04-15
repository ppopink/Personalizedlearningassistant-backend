import asyncio
from typing import List

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import client
from app.db.models import KnowledgeMastery, User
from app.schemas.agent import ChatRequest


def get_system_prompt_with_memory(username: str, db: Session):
    user = db.query(User).filter(User.username == username).first()
    weak_points = db.query(KnowledgeMastery).filter(
        KnowledgeMastery.user_id == (user.id if user else None),
        KnowledgeMastery.mastery_score < 60,
    ).all()

    memory_context = ""
    if user:
        memory_context += f"\n用户背景：{user.background}，学习目标：每天 {user.daily_goal_minutes} 分钟。"

    if weak_points:
        points_str = ", ".join([f"{p.point_name}({p.mastery_score}分, 易错点: {p.error_summary})" for p in weak_points])
        memory_context += f"\n注：以下知识点用户掌握较弱，请优先关注或在对话中复习：{points_str}"

    return f"你是一位资深的编程导师，说话幽默风趣。{memory_context}"


def _build_chat_messages(request: ChatRequest, db: Session):
    system_content = get_system_prompt_with_memory(request.username, db)
    messages = [{"role": "system", "content": system_content}]
    for msg in request.messages:
        messages.append({"role": msg.role, "content": msg.content})
    return messages


def chat_with_agent_flow(request: ChatRequest, db: Session):
    try:
        messages = _build_chat_messages(request, db)
        response = client.chat.completions.create(
            model="qwen-plus",
            messages=messages,
        )
        return {"status": "success", "reply": response.choices[0].message.content}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def chat_with_agent_stream_flow(request: ChatRequest, db: Session):
    async def generate_response():
        try:
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
                base_memory = get_system_prompt_with_memory(request.username, db)
                current_q_title = request.current_question.get("title", "未知")
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

            messages: List[dict] = [{"role": "system", "content": system_prompt}]
            for msg in request.messages:
                messages.append({"role": msg.role, "content": msg.content})

            response = client.chat.completions.create(
                model="qwen-plus",
                messages=messages,
                stream=True,
            )

            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content is not None:
                    content = chunk.choices[0].delta.content
                    yield f"data: {content}\n\n"
                    await asyncio.sleep(0.02)
        except Exception as exc:
            yield f"data: Error: {str(exc)}\n\n"

    return StreamingResponse(generate_response(), media_type="text/event-stream")
