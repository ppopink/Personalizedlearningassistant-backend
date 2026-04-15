from pydantic import BaseModel


class SyllabusRequest(BaseModel):
    user_id: str
    course_id: str
    course_name: str
    user_background: str
