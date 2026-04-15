from pydantic import BaseModel


class UserProfileRequest(BaseModel):
    username: str
    background: str
    daily_goal_minutes: int


class MasteryUpdateRequest(BaseModel):
    username: str
    point_name: str
    mastery_score: int
    error_summary: str = ""
