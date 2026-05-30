from __future__ import annotations

from ..retrieval.context_builder import ContextPackage
from .gemini_client import GeminiError, call_gemini
from .prompt_builder import build_prompt


def generate_answer(context: ContextPackage) -> str:
    prompt = build_prompt(context)
    try:
        answer = call_gemini(prompt)
    except GeminiError as exc:
        return _fallback_answer(context, str(exc))
    return answer or _fallback_answer(context, "Gemini returned an empty answer.")


def _fallback_answer(context: ContextPackage, reason: str) -> str:
    if context.agreements:
        lines = [
            "I found matching confirmed agreement rows in the stored data, but Gemini could not generate a full answer.",
            f"Reason: {reason}",
            "",
        ]
        for index, row in enumerate(context.agreements[:10], start=1):
            partner = row.get("partner_university", "")
            country = row.get("partner_country", "")
            home = row.get("home_university", "")
            source = row.get("source_url", "")
            lines.append(f"{index}. {partner} ({country}) from {home}. Source: {source}")
        return "\n".join(lines)

    if context.chunks:
        first = context.chunks[0]
        return (
            "I found related stored Erasmus information, but Gemini could not generate a full answer.\n"
            f"Reason: {reason}\n\n"
            f"Most relevant source: {first.get('title', '')}\n"
            f"{first.get('source_url', '')}"
        )

    return (
        "I could not find enough information in the stored Erasmus data to answer this question.\n"
        f"Gemini status: {reason}"
    )
