from pydantic import BaseModel


class QuestionRequest(BaseModel):
    course_id: str
    section_id: str
    section_title: str
