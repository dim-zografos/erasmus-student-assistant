from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(..., min_length=2)
    conversation_id: Optional[str] = None
    max_sources: int = Field(8, ge=1, le=20)


class Source(BaseModel):
    source_url: str
    title: str = ""
    university_key: str = ""
    university_name: str = ""
    category: str = ""
    document_id: Optional[int] = None
    chunk_id: Optional[int] = None
    snippet: str = ""


class AgreementResult(BaseModel):
    id: int
    home_university_key: str = ""
    home_university: str = ""
    department: str = ""
    partner_university: str = ""
    partner_country: str = ""
    deadline: str = ""
    academic_year: str = ""
    source_url: str = ""
    evidence_text: str = ""
    confidence: str = ""


class AskResponse(BaseModel):
    answer: str
    intent: str
    sources: List[Source] = []
    agreements: List[AgreementResult] = []
    data_notes: List[str] = []
    debug: Dict[str, Any] = {}


class HealthResponse(BaseModel):
    ok: bool
    db_path: str
    chroma_path: str
    gemini_configured: bool
    counts: Dict[str, int]
