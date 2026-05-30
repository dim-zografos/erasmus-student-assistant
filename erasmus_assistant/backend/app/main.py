from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .assistant.answer_generator import generate_answer
from .assistant.citations import source_items
from .config import ERASMUS_CHROMA_PATH, ERASMUS_DB_PATH, FRONTEND_ROOT, get_gemini_keys
from .data.chroma_reader import ChromaReader
from .data.sqlite_reader import ErasmusSQLiteReader
from .retrieval.context_builder import build_context
from .schemas import AgreementResult, AskRequest, AskResponse, HealthResponse, Source


app = FastAPI(title="Erasmus Assistant", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

reader = ErasmusSQLiteReader(ERASMUS_DB_PATH)
chroma = ChromaReader(ERASMUS_CHROMA_PATH)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        ok=True,
        db_path=str(ERASMUS_DB_PATH),
        chroma_path=str(ERASMUS_CHROMA_PATH),
        gemini_configured=bool(get_gemini_keys()),
        counts=reader.counts(),
    )


@app.get("/api/stats")
def stats():
    return reader.counts()


@app.get("/api/universities")
def universities():
    return reader.universities()


@app.post("/api/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    context = build_context(reader, chroma, request.question, max_sources=request.max_sources)
    answer = generate_answer(context)

    sources = [Source(**item) for item in source_items(context.chunks, limit=request.max_sources)]
    agreements = [AgreementResult(**row) for row in context.agreements[:25]]
    return AskResponse(
        answer=answer,
        intent=context.intent.name,
        sources=sources,
        agreements=agreements,
        data_notes=context.notes,
        debug={
            "university_keys": context.intent.university_keys,
            "partner_country": context.intent.partner_country,
            "agreement_rows": len(context.agreements),
            "knowledge_chunks": len(context.chunks),
        },
    )


@app.get("/")
def index():
    return FileResponse(FRONTEND_ROOT / "index.html")


app.mount("/assets", StaticFiles(directory=FRONTEND_ROOT), name="assets")
