from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.schemas.clerk import ClerkGenerateNoteRequest
from app.services.clerk_service import generate_clerk_note_flow


router = APIRouter(tags=["clerk"])


@router.post("/api/clerk/generate-note")
async def generate_clerk_note(request: ClerkGenerateNoteRequest, db: Session = Depends(get_db)):
    return generate_clerk_note_flow(request, db)
