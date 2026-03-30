# main.py
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from services.llm_client import get_ai_response # 引入 AI 服务

app = FastAPI(title="AI Agent 后端", version="1.0")

# 允许跨域（前端调用必配）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 定义请求体的数据格式
class ChatRequest(BaseModel):
    message: str

@app.post("/api/agent")
async def agent_chat(request: ChatRequest):
    # 这里真正去调用通义千问了！
    reply = await get_ai_response(request.message)
    
    return {
        "user_message": request.message,
        "ai_reply": reply
    }