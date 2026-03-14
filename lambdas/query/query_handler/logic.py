"""Business logic for the query_handler Lambda.

Checks access, validates twin status, embeds the query, searches
S3 Vectors, builds a RAG prompt, generates a response via Nova Pro,
and returns a structured QueryResult.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

RAG_SYSTEM_PROMPT = (
    "You are a knowledge retrieval assistant for {name}, who was a {role} "
    "in the {department} department. You have access to excerpts from their "
    "work emails dated between {tenure_start} and {offboard_date}.\n\n"
    "Rules:\n"
    "1. Answer ONLY from the provided context. Do not use general knowledge.\n"
    "2. For every factual claim, cite the source chunk ID and date in brackets.\n"
    "3. If the context does not contain sufficient information, say exactly: "
    '"I don\'t have information about that in {name}\'s knowledge base."\n'
    "4. Never invent technical details, system names, or decisions.\n"
    "5. If sources are older than 18 months, note that the information may be outdated."
)

STALENESS_MONTHS = 18


def check_access(
    user_id: str,
    employee_id: str,
    dynamo_module: Any,
) -> dict | None:
    """Return the access record or None if the user has no access."""
    return dynamo_module.check_access(user_id, employee_id)


def get_active_twin(
    employee_id: str,
    dynamo_module: Any,
) -> tuple[dict | None, str | None]:
    """Return (twin, error_code). error_code is None when twin is active."""
    twin = dynamo_module.get_twin(employee_id)
    if twin is None:
        return None, "TWIN_NOT_FOUND"
    if twin.get("status") != "active":
        return twin, "TWIN_NOT_ACTIVE"
    return twin, None


def embed_query(query_text: str, bedrock_module: Any) -> list[float]:
    """Embed the user query with GENERIC_RETRIEVAL purpose."""
    return bedrock_module.get_embedding(query_text, purpose="GENERIC_RETRIEVAL")


def search_vectors(
    query_embedding: list[float],
    employee_id: str,
    s3vectors_module: Any,
    top_k: int = 10,
) -> list[dict]:
    """Search S3 Vectors for chunks matching the employee."""
    return s3vectors_module.query_vectors(
        query_embedding=query_embedding,
        filter_expr={"employee_id": employee_id},
        top_k=top_k,
    )


def build_rag_prompt(twin: dict, query_text: str, chunks: list[dict]) -> str:
    """Build the user message containing retrieved context and the query."""
    context_parts: list[str] = []
    for chunk in chunks:
        metadata = chunk.get("metadata", {})
        chunk_key = chunk.get("key", "unknown")
        date = metadata.get("date", "unknown")
        subject = metadata.get("subject", "")
        content = metadata.get("content", "")
        context_parts.append(
            f"[{chunk_key} | {date}] Subject: {subject}\n{content}"
        )

    context_block = "\n\n---\n\n".join(context_parts) if context_parts else "(no context found)"

    return (
        f"Context:\n{context_block}\n\n"
        f"Question: {query_text}"
    )


def build_system_prompt(twin: dict) -> str:
    """Format the RAG system prompt with twin metadata."""
    return RAG_SYSTEM_PROMPT.format(
        name=twin.get("name", "Unknown"),
        role=twin.get("role", "Unknown"),
        department=twin.get("department", "Unknown"),
        tenure_start=twin.get("tenureStart", "Unknown"),
        offboard_date=twin.get("offboardDate", "Unknown"),
    )


def calculate_confidence(chunks: list[dict]) -> float:
    """Calculate confidence as average cosine similarity of returned chunks.

    S3 Vectors returns distance (lower = more similar for cosine).
    Cosine similarity = 1 - cosine_distance.
    """
    if not chunks:
        return 0.0

    similarities = []
    for chunk in chunks:
        distance = chunk.get("distance", 1.0)
        similarities.append(max(0.0, 1.0 - distance))

    return round(sum(similarities) / len(similarities), 4)


def check_staleness(chunks: list[dict]) -> str | None:
    """Return a warning string if the newest source is older than 18 months."""
    if not chunks:
        return "No source data available."

    dates: list[datetime] = []
    for chunk in chunks:
        date_str = chunk.get("metadata", {}).get("date")
        if date_str:
            try:
                parsed = datetime.fromisoformat(date_str)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                dates.append(parsed)
            except (ValueError, TypeError):
                continue

    if not dates:
        return "Unable to determine source freshness."

    newest = max(dates)
    now = datetime.now(timezone.utc)
    age_days = (now - newest).days
    staleness_threshold_days = STALENESS_MONTHS * 30  # approximate

    if age_days > staleness_threshold_days:
        return (
            f"The most recent source is from {newest.strftime('%Y-%m-%d')}, "
            f"which is over {STALENESS_MONTHS} months old. "
            "Information may be outdated."
        )
    return None


def format_sources(chunks: list[dict]) -> list[dict]:
    """Format chunk results into source references for the response."""
    sources = []
    for chunk in chunks:
        metadata = chunk.get("metadata", {})
        content = metadata.get("content", "")
        sources.append({
            "chunkId": chunk.get("key", ""),
            "date": metadata.get("date", ""),
            "subject": metadata.get("subject", ""),
            "contentPreview": content[:200] if content else "",
            "distance": chunk.get("distance", 0.0),
        })
    return sources


def execute_query(
    user_id: str,
    employee_id: str,
    query_text: str,
    request_id: str,
    *,
    dynamo_module: Any,
    bedrock_module: Any,
    s3vectors_module: Any,
) -> dict:
    """Execute the full RAG query pipeline.

    Returns a dict with either a successful result or an error.
    Structure on success: {"success": True, "data": {...}}
    Structure on error:   {"success": False, "status_code": int, "error": {...}}
    """
    # 1. Access check
    access = check_access(user_id, employee_id, dynamo_module)
    if access is None:
        return {
            "success": False,
            "status_code": 403,
            "error": {
                "code": "ACCESS_DENIED",
                "message": "Not authorized",
                "details": {},
            },
        }

    # 2. Twin status check
    twin, error_code = get_active_twin(employee_id, dynamo_module)
    if error_code == "TWIN_NOT_FOUND":
        return {
            "success": False,
            "status_code": 403,
            "error": {
                "code": "ACCESS_DENIED",
                "message": "Not authorized",
                "details": {},
            },
        }
    if error_code == "TWIN_NOT_ACTIVE":
        return {
            "success": False,
            "status_code": 400,
            "error": {
                "code": "TWIN_NOT_ACTIVE",
                "message": f"Twin is not available for querying (status: {twin.get('status')})",
                "details": {"status": twin.get("status", "unknown")},
            },
        }

    # 3. Embed query
    query_embedding = embed_query(query_text, bedrock_module)

    # 4. Vector search
    chunks = search_vectors(query_embedding, employee_id, s3vectors_module)

    # 5. Build prompts and generate
    system_prompt = build_system_prompt(twin)
    user_message = build_rag_prompt(twin, query_text, chunks)
    answer = bedrock_module.generate_response(system_prompt, user_message)

    # 6. Compute metadata
    confidence = calculate_confidence(chunks)
    staleness_warning = check_staleness(chunks)
    sources = format_sources(chunks)

    # 7. Audit log
    dynamo_module.write_audit_log(
        request_id=request_id,
        action="query",
        details={
            "employeeId": employee_id,
            "userId": user_id,
            "query": query_text,
            "chunkCount": len(chunks),
            "confidence": confidence,
        },
    )

    return {
        "success": True,
        "data": {
            "answer": answer,
            "sources": sources,
            "confidence": confidence,
            "staleness_warning": staleness_warning,
        },
    }
