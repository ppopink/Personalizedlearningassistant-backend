from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ConciergeRequest(BaseModel):
    user_id: str
    message: str
    current_page: Optional[str] = None
    course_id: Optional[str] = None
    allow_frontend_actions: bool = True
    available_frontend_actions: List[str] = Field(default_factory=list)
    context: Dict[str, Any] = Field(default_factory=dict)
