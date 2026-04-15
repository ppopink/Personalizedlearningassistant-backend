import os

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

QWEN_API_KEY = os.getenv("QWEN_API_KEY")
if not QWEN_API_KEY:
    raise ValueError("未找到 QWEN_API_KEY，请检查 .env 文件配置")

QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://my-ai-frontend.vercel.app",
]

client = OpenAI(
    api_key=QWEN_API_KEY,
    base_url=QWEN_BASE_URL,
)

