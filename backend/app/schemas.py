from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

MemoryCategory = Literal[
    "dietary_restriction",
    "allergy",
    "cuisine_preference",
    "budget",
    "merchant_preference",
]


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    memory_enabled: bool | None = None


class UserRead(OrmModel):
    id: UUID
    display_name: str
    memory_enabled: bool
    created_at: datetime


class SessionRead(OrmModel):
    id: UUID
    user_id: UUID
    status: str
    summary: str | None
    summary_data: dict[str, Any] | None
    summary_through_message_id: UUID | None
    started_at: datetime
    ended_at: datetime | None


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)


class MessageRead(OrmModel):
    id: UUID
    session_id: UUID
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class MemoryRead(OrmModel):
    id: UUID
    user_id: UUID
    category: MemoryCategory
    value: dict[str, Any]
    description: str
    source_type: Literal["explicit", "inferred"]
    confidence: float
    status: Literal["candidate", "active", "superseded"]
    created_at: datetime
    updated_at: datetime
    evidence: list[MessageRead] = []


class MemoryCorrection(BaseModel):
    value: dict[str, Any]
    description: str = Field(min_length=1, max_length=500)


class PersonaRead(OrmModel):
    id: UUID
    user_id: UUID
    version: int
    profile: dict[str, Any]
    summary: str
    created_at: datetime


class ChatResponse(BaseModel):
    message: MessageRead
    memories_used: list[MemoryRead]
    summary_updated: bool


class EndSessionResponse(BaseModel):
    session: SessionRead
    memories: list[MemoryRead]
    persona: PersonaRead


class SessionSummaryOutput(BaseModel):
    summary: str
    current_goal: str | None
    temporary_constraints: list[str]
    unresolved_questions: list[str]
    discussed_merchants: list[str]
    possible_memory_candidates: list[str]


class MemoryCandidate(BaseModel):
    category: MemoryCategory
    normalized_value: str
    sentiment: Literal["likes", "dislikes", "neutral"] | None
    amount: float | None
    currency: str | None
    context: str | None
    description: str
    source_type: Literal["explicit", "inferred"]
    evidence_message_ids: list[UUID]
    durable: bool
    subject_is_user: bool


class MemoryExtraction(BaseModel):
    candidates: list[MemoryCandidate]


class PersonaSummaryOutput(BaseModel):
    summary: str
