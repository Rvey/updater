import logging

import httpx

from .config import get_settings
from .db import Update

logger = logging.getLogger(__name__)


def _format_excerpts(update: Update) -> str:
    excerpts = [item for item in (update.code_context or []) if isinstance(item, dict) and item.get("content")]
    if not excerpts:
        return "Code excerpts: none attached yet. If the question needs code detail, say so and suggest requesting context from the connected agent."
    blocks = []
    for item in excerpts[:8]:
        path = item.get("path", "unknown file")
        start = item.get("start_line")
        end = item.get("end_line")
        span = f" (lines {start}-{end})" if start and end else ""
        blocks.append(f"--- {path}{span} ---\n{item.get('content', '')[:6000]}")
    return "Code excerpts from the connected agent:\n" + "\n".join(blocks)


def saved_context(update: Update) -> str:
    return "\n".join(
        [
            f"Title: {update.title}",
            f"Summary: {update.summary}",
            f"Why: {update.why}",
            f"How it works: {update.how_it_works}",
            f"Impact: {update.impact}",
            f"Tradeoffs: {update.tradeoffs or 'Not recorded'}",
            f"Learning notes: {update.learning_notes or 'Not recorded'}",
            f"Files: {', '.join(update.files_changed) or 'Not recorded'}",
            f"Repository: {update.repo_url}",
            f"Commit: {update.commit_sha or 'Not recorded'}",
            _format_excerpts(update),
        ]
    )


async def explain_question(update: Update, question: str) -> tuple[str, str]:
    settings = get_settings()
    context = saved_context(update)
    if settings.openrouter_api_key:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
                    json={
                        "model": settings.llm_model,
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "You are a patient coding mentor. Explain this shipped feature to its owner using the "
                                    "saved feature context and any code excerpts provided by the connected agent. Be concrete "
                                    "and concise, and cite the excerpt paths you rely on. If the excerpts are missing and the "
                                    "question needs code detail, say what is missing and suggest requesting context from the "
                                    "connected agent. Never invent code you were not given."
                                ),
                            },
                            {"role": "user", "content": f"Saved feature context:\n{context}\n\nQuestion: {question}"},
                        ],
                    },
                )
                response.raise_for_status()
                answer = response.json()["choices"][0]["message"]["content"]
                if isinstance(answer, str) and answer.strip():
                    return answer.strip(), "ai"
        except Exception:
            logger.exception("Explanation request failed; returning saved context")

    lowered = question.lower()
    if any(word in lowered for word in ("why", "reason", "motivation")):
        answer = f"The recorded reason was: {update.why}"
    elif any(word in lowered for word in ("impact", "affect", "change for", "benefit")):
        answer = f"The expected impact is: {update.impact}"
    elif any(word in lowered for word in ("tradeoff", "risk", "limitation")):
        answer = f"Recorded tradeoffs: {update.tradeoffs or 'None were recorded.'}"
    elif any(word in lowered for word in ("file", "code", "where")):
        answer = f"Files recorded: {', '.join(update.files_changed) or 'No file list was recorded.'} How it works: {update.how_it_works}"
    else:
        answer = f"From the saved implementation context: {update.how_it_works}"
    return answer + "\n\nFor deeper follow-up explanations, configure OPENROUTER_API_KEY.", "saved-context"
