from pydantic import BaseModel


class NoteRequest(BaseModel):
    course_name: str
    learned_topics: str
    weak_points: str


class MindmapOnlyRequest(BaseModel):
    content: str


class CreateNoteRequest(BaseModel):
    user_id: str
    course_id: str
    title: str
    content: str
