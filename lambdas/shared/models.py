"""Pydantic data models for KnowledgeKeeper."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class Twin(BaseModel):
    """Digital twin metadata stored in KKTwins DynamoDB table."""

    employee_id: str = Field(alias="employeeId")
    name: str
    email: str
    role: str
    department: str
    tenure_start: date | None = Field(default=None, alias="tenureStart")
    offboard_date: date = Field(alias="offboardDate")
    chunk_count: int = Field(default=0, alias="chunkCount")
    topic_index: list[str] = Field(default_factory=list, alias="topicIndex")
    status: Literal[
        "ingesting", "processing", "embedding", "active", "error", "expired", "deleted"
    ] = "ingesting"
    retention_expiry: date | None = Field(default=None, alias="retentionExpiry")
    provider: Literal["google", "upload", "microsoft"] = "upload"

    model_config = {"populate_by_name": True}


class EmailChunk(BaseModel):
    """A single embedded chunk stored in S3 Vectors."""

    chunk_id: str = Field(alias="chunkId")
    employee_id: str = Field(alias="employeeId")
    thread_id: str = Field(alias="threadId")
    subject: str
    date: datetime
    author_role: Literal["primary", "cc", "bcc"] = Field(alias="authorRole")
    content: str
    relevance_score: float = Field(default=0.0, alias="relevanceScore")
    embedding_model: str = Field(
        default="amazon.nova-2-multimodal-embeddings-v1:0", alias="embeddingModel"
    )
    topics: list[str] = Field(default_factory=list)
    pii_unverified: bool = Field(default=False, alias="piiUnverified")

    model_config = {"populate_by_name": True}


class ChunkReference(BaseModel):
    """A source reference returned in query results."""

    chunk_id: str = Field(alias="chunkId")
    date: str
    subject: str
    content_preview: str = Field(default="", alias="contentPreview")
    distance: float = 0.0

    model_config = {"populate_by_name": True}


class QueryResult(BaseModel):
    """Response from the RAG query pipeline."""

    answer: str
    sources: list[ChunkReference] = Field(default_factory=list)
    confidence: float = 0.0
    staleness_warning: str | None = None
