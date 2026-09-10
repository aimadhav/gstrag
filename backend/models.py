from datetime import date, datetime
from pydantic import BaseModel, Field

class Chunk(BaseModel):
    id: str
    document_id: str
    document_title: str
    source_type: str
    content: str
    page_number: int | None = None
    section_path: list[str] = Field(default_factory=list)
    publication_date: date | None = None
    effective_date: date | None = None
    similarity: float = 0.0

class ChatRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)

class Citation(BaseModel):
    document_id: str
    document_title: str
    page_number: int | None = None

class ChatResponse(BaseModel):
    answer: str
    status: str
    citations: list[Citation] = Field(default_factory=list)
    review_reason: str | None = None
    trace_id: str | None = None
