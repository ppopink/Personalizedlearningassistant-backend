from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 初始化后端应用
app = FastAPI(title="AI Agent 后端", version="1.0")

# 允许前端访问（前后端必备）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------
# 测试接口（看看后端活没活）
# ----------------------
@app.get("/")
def home():
    return {
        "status": "运行成功",
        "message": "AI Agent 后端已启动！"
    }

# ----------------------
# AI Agent 核心接口
# ----------------------
@app.post("/api/agent")
def agent_chat(message: str):
    # 这里未来可以接 GPT / 通义千问 / 本地大模型
    reply = f"AI 已收到：{message}，我是你的智能助手！"

    return {
        "user_message": message,
        "ai_reply": reply
    }