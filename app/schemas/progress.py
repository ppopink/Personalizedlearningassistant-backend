from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ProgressUpdateRequest(BaseModel):
    user_id: str
    course_id: str
    current_chapter_id: Optional[str] = None
    current_chapter_title: Optional[str] = None
    current_section_id: Optional[str] = None
    current_section_title: Optional[str] = None
    completed_chapter_ids: List[str] = Field(default_factory=list)
    completed_section_ids: List[str] = Field(default_factory=list)
    event_type: str = "progress_update"
    progress_meta: Dict[str, Any] = Field(default_factory=dict)
