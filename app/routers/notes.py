from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.schemas.notes import CreateNoteRequest, MindmapOnlyRequest, NoteRequest
from app.services.notes_service import (
    extract_mindmap_flow,
    generate_review_note_flow,
    get_user_notes_list_flow,
    save_user_note_flow,
)


router = APIRouter(tags=["notes"])


@router.post("/api/notes/generate")
async def generate_review_note(request: NoteRequest):
    return generate_review_note_flow(request)


@router.post("/api/notes/extract-mindmap")
async def extract_mindmap(request: MindmapOnlyRequest):
    return extract_mindmap_flow(request)


@router.post("/api/notes/save")
async def save_user_note(request: CreateNoteRequest, db: Session = Depends(get_db)):
    return save_user_note_flow(request, db)


@router.get("/api/notes/list/{user_id}")
async def get_user_notes_list(user_id: str, db: Session = Depends(get_db)):
    return get_user_notes_list_flow(user_id, db)
