from __future__ import annotations

from typing import Any, Dict, List

from ..retrieval.context_builder import ContextPackage


def build_prompt(context: ContextPackage) -> str:
    agreements_block = _agreements_block(context.agreements)
    chunks_block = _chunks_block(context.chunks)
    notes_block = "\n".join(f"- {note}" for note in context.notes) or "- No retrieval notes."

    return f"""
You are an Erasmus student assistant for Greek universities.

Answer the student's question using only the retrieved data below.

Rules:
- Do not invent partner universities, deadlines, countries, requirements, departments, or procedures.
- If the retrieved data does not contain the answer, say that the stored data does not contain enough information.
- Prefer confirmed agreement rows for partner-university questions.
- Use general knowledge chunks only for explanations, requirements, deadlines, and procedures.
- Cite sources with labels like [S1], [S2]. Use [A1], [A2] for structured agreement rows.
- Keep the answer practical and student-friendly.

Student question:
{context.question}

Detected intent:
{context.intent.name}

Retrieval notes:
{notes_block}

Confirmed agreement rows:
{agreements_block}

Knowledge sources:
{chunks_block}
""".strip()


def _agreements_block(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "No confirmed agreement rows retrieved."
    lines = []
    for index, row in enumerate(rows, start=1):
        fields = [
            f"home={row.get('home_university', '')}",
            f"department={row.get('department', '')}",
            f"partner={row.get('partner_university', '')}",
            f"country={row.get('partner_country', '')}",
            f"deadline={row.get('deadline', '')}",
            f"academic_year={row.get('academic_year', '')}",
            f"confidence={row.get('confidence', '')}",
            f"source_url={row.get('source_url', '')}",
            f"evidence={row.get('evidence_text', '')}",
        ]
        lines.append(f"[A{index}] " + " | ".join(fields))
    return "\n".join(lines)


def _chunks_block(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "No knowledge chunks retrieved."
    lines = []
    for index, row in enumerate(rows, start=1):
        text = " ".join(str(row.get("chunk_text", "")).split())
        if len(text) > 1300:
            text = text[:1297].rstrip() + "..."
        lines.append(
            f"[S{index}] title={row.get('title', '')} | university={row.get('university_name', '')} "
            f"| category={row.get('category', '')} | source_url={row.get('source_url', '')}\n{text}"
        )
    return "\n\n".join(lines)
