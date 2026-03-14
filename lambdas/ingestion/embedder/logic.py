"""Business logic for the embedder Lambda.

Chunks cleaned email threads at sentence boundaries, generates embeddings
via Amazon Nova Multimodal Embeddings, and indexes chunks in S3 Vectors.
Updates Twin status in DynamoDB on completion.
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

MAX_TOKENS = 512
OVERLAP_TOKENS = 64

# Rough approximation: 1 token ≈ 4 characters for English text.
_CHARS_PER_TOKEN = 4

# Sentence boundary pattern — splits on period/question/exclamation followed
# by whitespace, while avoiding splits on common abbreviations.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _estimate_tokens(text: str) -> int:
    """Estimate token count using character-based heuristic."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


def split_into_sentences(text: str) -> list[str]:
    """Split text into sentences at punctuation boundaries."""
    sentences = _SENTENCE_SPLIT.split(text.strip())
    return [s for s in sentences if s.strip()]


def chunk_thread(thread: dict[str, Any]) -> list[dict[str, Any]]:
    """Chunk a cleaned thread into overlapping segments for embedding.

    Each chunk is at most MAX_TOKENS tokens with OVERLAP_TOKENS overlap.
    Boundaries align to sentence breaks where possible.

    Returns a list of chunk dicts with metadata ready for embedding.
    """
    employee_id = thread.get("employeeId", "")
    thread_id = thread.get("threadId", "")
    subject = thread.get("subject", "")

    # Concatenate all message bodies into a single text block with metadata.
    full_text = _build_full_text(thread)
    if not full_text.strip():
        return []

    sentences = split_into_sentences(full_text)
    if not sentences:
        return []

    chunks: list[dict[str, Any]] = []
    current_sentences: list[str] = []
    current_tokens = 0

    for sentence in sentences:
        sentence_tokens = _estimate_tokens(sentence)

        if current_tokens + sentence_tokens > MAX_TOKENS and current_sentences:
            chunk_text = " ".join(current_sentences)
            chunks.append(_build_chunk_meta(
                chunk_text, employee_id, thread_id, subject, thread,
            ))

            # Keep overlap: walk backwards to find sentences within overlap budget.
            overlap_sentences: list[str] = []
            overlap_tokens = 0
            for s in reversed(current_sentences):
                s_tokens = _estimate_tokens(s)
                if overlap_tokens + s_tokens > OVERLAP_TOKENS:
                    break
                overlap_sentences.insert(0, s)
                overlap_tokens += s_tokens

            current_sentences = overlap_sentences
            current_tokens = overlap_tokens

        current_sentences.append(sentence)
        current_tokens += sentence_tokens

    # Flush remaining sentences as the final chunk.
    if current_sentences:
        chunk_text = " ".join(current_sentences)
        chunks.append(_build_chunk_meta(
            chunk_text, employee_id, thread_id, subject, thread,
        ))

    return chunks


def _build_full_text(thread: dict[str, Any]) -> str:
    """Concatenate message bodies with author/date context."""
    parts: list[str] = []
    for msg in thread.get("messages", []):
        body = msg.get("body_text", "").strip()
        if body:
            parts.append(body)
    return "\n\n".join(parts)


def _build_chunk_meta(
    text: str,
    employee_id: str,
    thread_id: str,
    subject: str,
    thread: dict[str, Any],
) -> dict[str, Any]:
    """Build a chunk dict with all metadata needed for S3 Vectors."""
    # Derive author_role and date from the first message in the thread.
    messages = thread.get("messages", [])
    author_role = messages[0].get("author_role", "primary") if messages else "primary"
    date = messages[0].get("date", "") if messages else ""

    return {
        "chunk_id": f"{employee_id}_{thread_id}_{uuid.uuid4().hex[:12]}",
        "employee_id": employee_id,
        "thread_id": thread_id,
        "subject": subject,
        "author_role": author_role,
        "date": date,
        "content": text,
    }


def embed_and_index_chunks(
    chunks: list[dict[str, Any]],
    bedrock_client=None,
    s3vectors_client=None,
    vector_bucket_name: str = "",
    vector_index_name: str = "",
    get_embedding_fn=None,
    put_vectors_fn=None,
) -> int:
    """Embed each chunk and store in S3 Vectors.

    Retries failed Bedrock/S3Vectors calls up to 3 times with exponential
    backoff. Raises on final failure so the SQS message goes to DLQ.

    Returns the number of chunks successfully indexed.
    """
    if get_embedding_fn is None:
        from shared.bedrock import get_embedding
        get_embedding_fn = get_embedding
    if put_vectors_fn is None:
        from shared.s3vectors_client import put_vectors
        put_vectors_fn = put_vectors

    get_emb = get_embedding_fn
    put_vec = put_vectors_fn

    indexed = 0

    for chunk in chunks:
        # --- Embed with retry ---
        embedding = _retry(
            lambda c=chunk: get_emb(
                c["content"],
                purpose="GENERIC_INDEX",
                dimension=1024,
                client=bedrock_client,
            ),
            description=f"embed chunk {chunk['chunk_id']}",
        )

        # --- Index with retry ---
        vector_record = {
            "key": chunk["chunk_id"],
            "data": {"float32": embedding},
            "metadata": {
                "employee_id": chunk["employee_id"],
                "thread_id": chunk["thread_id"],
                "author_role": chunk["author_role"],
                "date": chunk["date"],
                "content": chunk["content"],
                "subject": chunk["subject"],
            },
        }

        _retry(
            lambda rec=vector_record: put_vec(
                vectors=[rec],
                bucket_name=vector_bucket_name or None,
                index_name=vector_index_name or None,
                client=s3vectors_client,
            ),
            description=f"put_vectors chunk {chunk['chunk_id']}",
        )

        indexed += 1

    return indexed


def update_twin_status(
    employee_id: str,
    chunk_count: int,
    update_twin_fn=None,
) -> dict[str, Any]:
    """Set Twin status to 'active' and record chunk_count."""
    if update_twin_fn is None:
        from shared.dynamo import update_twin
        update_twin_fn = update_twin

    return update_twin_fn(employee_id, {
        "status": "active",
        "chunkCount": chunk_count,
    })


def _retry(fn, max_retries: int = 3, description: str = "") -> Any:
    """Call *fn* with exponential backoff. Raises on final failure."""
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception:
            if attempt == max_retries - 1:
                logger.exception(
                    "Final retry failed for %s", description,
                )
                raise
            wait = 2 ** attempt
            logger.warning(
                "Attempt %d/%d failed for %s — retrying in %ds",
                attempt + 1, max_retries, description, wait,
            )
            time.sleep(wait)
