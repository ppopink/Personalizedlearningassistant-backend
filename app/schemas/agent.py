from typing import Dict, List, Optional

from pydantic import BaseModel

from app.schemas.common import ChatMessage


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    username: str = "default_user"
    current_question: Optional[Dict] = None
    persona: str = "鼓励型"
