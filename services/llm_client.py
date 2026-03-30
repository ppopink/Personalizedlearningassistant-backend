# services/llm_client.py
import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

# 加载 .env 环境变量
load_dotenv()

# 初始化异步客户端
client = AsyncOpenAI(
    api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("LLM_BASE_URL")
)
model_name = os.getenv("LLM_MODEL_NAME")

async def get_ai_response(user_message: str) -> str:
    """调用大模型获取回复"""
    try:
        response = await client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "你是一位专业的编程导师，负责解答初学者的问题。"},
                {"role": "user", "content": user_message}
            ],
            temperature=0.7,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI 调用出错了: {str(e)}"