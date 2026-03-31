import os
import json
import asyncio
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI
from sqlalchemy.orm import Session
from database import SessionLocal, User, KnowledgeMastery, UserSyllabus, init_db

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
        "https://你的前端名字.vercel.app",   # 🚨 请将此处替换为你真实的 Vercel 部署域名！
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

# 5. 定义数据格式
class ChatRequest(BaseModel):
    message: str
    username: str = "default_user" # 临时默认用户

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

# 定义答题导师接收的数据格式 (加入了题目上下文)
class TutorRequest(BaseModel):
    question_context: str  # 当前这道题的题干和选项
    user_action: str       # 用户的行为 (例如："选错了D" 或 "点击了[给个提示]")
    message: str           # 用户具体输入的话
    tutor_style: str = "鼓励引导型"  # 🚨 新增：导师风格

# 定义前端传过来的学习情况总结数据
class NoteRequest(BaseModel):
    course_name: str       # 例如："Python 基础"
    learned_topics: str    # 例如："变量与数据类型、运算符"
    weak_points: str       # 例如："经常忘记给字符串加引号"

# 定义脑图提取请求体
class MindmapOnlyRequest(BaseModel):
    content: str  # 用户自己写的笔记内容

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

# 7. 编写测试对话接口
@app.post("/api/agent/chat")
async def chat_with_agent(request: ChatRequest, db: Session = Depends(get_db)):
    try:
        system_content = get_system_prompt_with_memory(request.username, db)
        
        # 组装消息，加入 System Prompt 设定它的角色
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": request.message}
        ]

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
            system_content = get_system_prompt_with_memory(request.username, db)
            
            messages = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": request.message}
            ]
            
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

# 13. 新增：答题导师专属流式接口 (Context-Aware)
@app.post("/api/study/tutor-chat/stream")
async def tutor_chat_stream(request: TutorRequest):
    async def generate_response():
        # 🚨 核心魔法：预设三种不同人设的 Prompt 字典
        style_prompts = {
            "鼓励引导型": "语气要极其温柔、充满鼓励，多用肯定词汇（如'你的思路很棒'）。像一位充满耐心的金牌导师，循循善诱，可以适当使用温暖的 emoji。",
            "精炼直接型": "语气要冷峻、专业、极度精炼。拒绝任何废话、寒暄和客套，直击知识盲区，字数严格控制在30字以内。",
            "幽默风趣型": "语气要极其幽默、接地气，甚至带点脱口秀式的吐槽（但不伤人）。喜欢用搞笑的互联网梗或生活中的奇妙比喻来解释编程概念。"
        }
        
        # 根据前端传来的风格，提取对应的人设说明（如果乱传，就默认鼓励型）
        current_persona = style_prompts.get(request.tutor_style, style_prompts["鼓励引导型"])

        # 把这个人设动态拼接到 System Prompt 里！
        system_prompt = f"""
        你是一位编程私教。用户正在做一道选择题。
        【当前题目上下文】：{request.question_context}
        【用户当前状态】：{request.user_action}
        
        【你的专属人设设定】（必须严格扮演）：
        {current_persona}
        
        通用铁律：绝对不直接给正确答案字母！帮他分析错因，并给出思考方向。
        """
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request.message}
        ]
        
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

@app.get("/")
async def root():
    return {"message": "AI 后端服务已启动！"}