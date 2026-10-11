from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, engine, get_db
from .llm import extract_memories, generate_chat, summarize_session
from .memory import apply_candidates, evidence_for_memory, regenerate_persona
from .models import ConversationSession, Memory, Message, Persona, User
from .schemas import (
    ChatResponse,
    EndSessionResponse,
    MemoryCorrection,
    MemoryRead,
    MessageCreate,
    MessageRead,
    PersonaRead,
    SessionRead,
    UserCreate,
    UserRead,
    UserUpdate,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(
    title="Commerce Memory Assistant API",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list({settings.frontend_origin, "http://127.0.0.1:5173"}),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

Db = Annotated[Session, Depends(get_db)]


def require_user(db: Session, user_id: UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def require_session(db: Session, session_id: UUID) -> ConversationSession:
    conversation = db.get(ConversationSession, session_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return conversation


def require_memory(db: Session, memory_id: UUID) -> Memory:
    memory = db.get(Memory, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory


def memory_read(db: Session, memory: Memory) -> MemoryRead:
    data = MemoryRead.model_validate(memory)
    return data.model_copy(
        update={
            "confidence": float(memory.confidence),
            "evidence": [
                MessageRead.model_validate(message)
                for message in evidence_for_memory(db, memory.id)
            ],
        }
    )


def active_memories(db: Session, user: User) -> list[Memory]:
    if not user.memory_enabled:
        return []
    return list(
        db.scalars(
            select(Memory)
            .where(Memory.user_id == user.id, Memory.status == "active")
            .order_by(Memory.created_at)
        )
    )


def unsummarized_messages(messages: list[Message], checkpoint_id: UUID | None) -> list[Message]:
    if checkpoint_id is None:
        return messages
    for index, message in enumerate(messages):
        if message.id == checkpoint_id:
            return messages[index + 1 :]
    return messages


def update_summary(conversation: ConversationSession, messages: list[Message]) -> None:
    recent = unsummarized_messages(messages, conversation.summary_through_message_id)
    if not recent:
        return
    output = summarize_session(conversation.summary, conversation.summary_data, recent)
    conversation.summary = output.summary
    conversation.summary_data = output.model_dump(exclude={"summary"})
    conversation.summary_through_message_id = messages[-1].id


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "llm_mode": settings.llm_mode}


@app.post("/api/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: Db) -> User:
    user = User(display_name=payload.display_name.strip())
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.get("/api/users", response_model=list[UserRead])
def list_users(db: Db) -> list[User]:
    return list(db.scalars(select(User).order_by(User.created_at)))


@app.get("/api/users/{user_id}", response_model=UserRead)
def get_user(user_id: UUID, db: Db) -> User:
    return require_user(db, user_id)


@app.patch("/api/users/{user_id}", response_model=UserRead)
def update_user(user_id: UUID, payload: UserUpdate, db: Db) -> User:
    user = require_user(db, user_id)
    if payload.display_name is not None:
        user.display_name = payload.display_name.strip()
    if payload.memory_enabled is not None:
        user.memory_enabled = payload.memory_enabled
    db.commit()
    db.refresh(user)
    return user


@app.post(
    "/api/users/{user_id}/sessions",
    response_model=SessionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_session(user_id: UUID, db: Db) -> ConversationSession:
    require_user(db, user_id)
    conversation = ConversationSession(user_id=user_id)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


@app.get("/api/users/{user_id}/sessions", response_model=list[SessionRead])
def list_sessions(user_id: UUID, db: Db) -> list[ConversationSession]:
    require_user(db, user_id)
    return list(
        db.scalars(
            select(ConversationSession)
            .where(ConversationSession.user_id == user_id)
            .order_by(ConversationSession.started_at.desc())
        )
    )


@app.get("/api/sessions/{session_id}", response_model=SessionRead)
def get_session(session_id: UUID, db: Db) -> ConversationSession:
    return require_session(db, session_id)


@app.get("/api/sessions/{session_id}/messages", response_model=list[MessageRead])
def list_messages(session_id: UUID, db: Db) -> list[Message]:
    require_session(db, session_id)
    return list(
        db.scalars(
            select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
        )
    )


@app.post("/api/sessions/{session_id}/messages", response_model=ChatResponse)
def send_message(
    session_id: UUID,
    payload: MessageCreate,
    db: Db,
) -> ChatResponse:
    conversation = require_session(db, session_id)
    if conversation.status != "active":
        raise HTTPException(status_code=409, detail="This session is already closed")
    user = require_user(db, conversation.user_id)

    user_message = Message(
        session_id=session_id,
        role="user",
        content=payload.content.strip(),
    )
    db.add(user_message)
    db.flush()

    history = list(
        db.scalars(
            select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
        )
    )
    memories = active_memories(db, user)
    assistant_message = Message(
        session_id=session_id,
        role="assistant",
        content=generate_chat(history, memories, conversation.summary),
    )
    db.add(assistant_message)
    db.flush()

    history.append(assistant_message)
    recent = unsummarized_messages(history, conversation.summary_through_message_id)
    should_summarize = sum(message.role == "user" for message in recent) >= 10
    if should_summarize:
        update_summary(conversation, history)

    db.commit()
    db.refresh(assistant_message)
    return ChatResponse(
        message=MessageRead.model_validate(assistant_message),
        memories_used=[memory_read(db, memory) for memory in memories],
        summary_updated=should_summarize,
    )


@app.post("/api/sessions/{session_id}/end", response_model=EndSessionResponse)
def end_session(session_id: UUID, db: Db) -> EndSessionResponse:
    conversation = require_session(db, session_id)
    user = require_user(db, conversation.user_id)
    if conversation.status == "closed":
        persona = db.scalar(
            select(Persona).where(Persona.user_id == user.id).order_by(Persona.version.desc())
        )
        if persona is None:
            persona = regenerate_persona(db, user.id)
            db.commit()
        memories = active_memories(db, user)
        return EndSessionResponse(
            session=SessionRead.model_validate(conversation),
            memories=[memory_read(db, memory) for memory in memories],
            persona=PersonaRead.model_validate(persona),
        )

    conversation.status = "processing"
    conversation.ended_at = datetime.now(UTC)
    messages = list(
        db.scalars(
            select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
        )
    )
    if messages:
        update_summary(conversation, messages)
        extraction = extract_memories(messages)
        apply_candidates(db, user, conversation, extraction.candidates)

    persona = regenerate_persona(db, user.id)
    conversation.status = "closed"
    db.commit()
    db.refresh(conversation)
    memories = list(
        db.scalars(select(Memory).where(Memory.user_id == user.id).order_by(Memory.created_at))
    )
    return EndSessionResponse(
        session=SessionRead.model_validate(conversation),
        memories=[memory_read(db, memory) for memory in memories],
        persona=PersonaRead.model_validate(persona),
    )


@app.get("/api/users/{user_id}/memories", response_model=list[MemoryRead])
def list_memories(user_id: UUID, db: Db) -> list[MemoryRead]:
    require_user(db, user_id)
    memories = list(
        db.scalars(
            select(Memory).where(Memory.user_id == user_id).order_by(Memory.updated_at.desc())
        )
    )
    return [memory_read(db, memory) for memory in memories]


@app.patch("/api/memories/{memory_id}", response_model=MemoryRead)
def correct_memory(
    memory_id: UUID,
    payload: MemoryCorrection,
    db: Db,
) -> MemoryRead:
    old = require_memory(db, memory_id)
    old.status = "superseded"
    old.updated_at = datetime.now(UTC)
    corrected = Memory(
        user_id=old.user_id,
        category=old.category,
        value=payload.value,
        description=payload.description.strip(),
        source_type="explicit",
        confidence=Decimal("1.00"),
        status="active",
    )
    db.add(corrected)
    db.flush()
    regenerate_persona(db, old.user_id)
    db.commit()
    db.refresh(corrected)
    return memory_read(db, corrected)


@app.post("/api/memories/{memory_id}/confirm", response_model=MemoryRead)
def confirm_memory(memory_id: UUID, db: Db) -> MemoryRead:
    memory = require_memory(db, memory_id)
    memory.source_type = "explicit"
    memory.confidence = Decimal("1.00")
    memory.status = "active"
    memory.updated_at = datetime.now(UTC)
    regenerate_persona(db, memory.user_id)
    db.commit()
    db.refresh(memory)
    return memory_read(db, memory)


@app.delete("/api/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(memory_id: UUID, db: Db) -> Response:
    memory = require_memory(db, memory_id)
    user_id = memory.user_id
    db.delete(memory)
    db.flush()
    regenerate_persona(db, user_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/users/{user_id}/persona", response_model=PersonaRead)
def get_persona(user_id: UUID, db: Db) -> Persona:
    require_user(db, user_id)
    persona = db.scalar(
        select(Persona).where(Persona.user_id == user_id).order_by(Persona.version.desc())
    )
    if persona is None:
        persona = regenerate_persona(db, user_id)
        db.commit()
        db.refresh(persona)
    return persona
