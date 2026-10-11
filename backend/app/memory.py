import json
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .llm import generate_persona_summary
from .models import ConversationSession, Memory, MemorySource, Message, Persona, User, utcnow
from .schemas import MemoryCandidate

SAFETY_CATEGORIES = {"allergy", "dietary_restriction"}
ALLOWED_CATEGORIES = SAFETY_CATEGORIES | {
    "cuisine_preference",
    "budget",
    "merchant_preference",
}


def candidate_value(candidate: MemoryCandidate) -> dict:
    if candidate.category in SAFETY_CATEGORIES:
        return {"name": candidate.normalized_value}
    if candidate.category in {"cuisine_preference", "merchant_preference"}:
        return {
            "name": candidate.normalized_value,
            "sentiment": candidate.sentiment or "likes",
        }
    return {
        "maximum": candidate.amount,
        "currency": candidate.currency or "USD",
        "context": candidate.context or "meal",
    }


def _key(category: str, value: dict) -> str:
    return f"{category}:{json.dumps(value, sort_keys=True, separators=(',', ':')).lower()}"


def apply_candidates(
    db: Session,
    user: User,
    session: ConversationSession,
    candidates: list[MemoryCandidate],
) -> list[Memory]:
    if not user.memory_enabled:
        return []

    user_messages = {message.id: message for message in session.messages if message.role == "user"}
    memories = list(
        db.scalars(
            select(Memory)
            .where(Memory.user_id == user.id, Memory.status != "superseded")
            .options(selectinload(Memory.sources).selectinload(MemorySource.message))
        )
    )
    by_key = {_key(memory.category, memory.value): memory for memory in memories}
    accepted: list[Memory] = []

    for candidate in candidates:
        evidence = [
            user_messages[message_id]
            for message_id in dict.fromkeys(candidate.evidence_message_ids)
            if message_id in user_messages
        ]
        if (
            candidate.category not in ALLOWED_CATEGORIES
            or not candidate.durable
            or not candidate.subject_is_user
            or not evidence
            or (candidate.category in SAFETY_CATEGORIES and candidate.source_type != "explicit")
            or (candidate.category == "budget" and candidate.amount is None)
        ):
            continue

        value = candidate_value(candidate)
        key = _key(candidate.category, value)
        memory = by_key.get(key)
        if memory is None:
            memory = Memory(
                user_id=user.id,
                category=candidate.category,
                value=value,
                description=candidate.description,
                source_type=candidate.source_type,
                confidence=Decimal("1.00")
                if candidate.source_type == "explicit"
                else Decimal("0.50"),
                status="active" if candidate.source_type == "explicit" else "candidate",
            )
            db.add(memory)
            db.flush()
            by_key[key] = memory

        known_source_ids = {source.message_id for source in memory.sources}
        for message in evidence:
            if message.id not in known_source_ids:
                source = MemorySource(memory_id=memory.id, message_id=message.id)
                db.add(source)
                memory.sources.append(source)

        if candidate.source_type == "explicit" or memory.source_type == "explicit":
            memory.source_type = "explicit"
            memory.confidence = Decimal("1.00")
            memory.status = "active"
            if candidate.source_type == "explicit":
                memory.description = candidate.description
        else:
            session_ids = {
                source.message.session_id for source in memory.sources if source.message is not None
            }
            session_ids.add(session.id)
            count = len(session_ids)
            memory.confidence = Decimal("0.80" if count >= 3 else "0.70" if count >= 2 else "0.50")
            memory.status = "active" if count >= 2 else "candidate"
        memory.updated_at = utcnow()
        accepted.append(memory)

    db.flush()
    return accepted


def profile_from_memories(memories: list[Memory]) -> dict:
    profile = {
        "dietary": [],
        "allergies": [],
        "liked_cuisines": [],
        "disliked_cuisines": [],
        "budgets": [],
        "preferred_merchants": [],
    }
    for memory in memories:
        value = memory.value
        if memory.category == "dietary_restriction":
            profile["dietary"].append(value["name"])
        elif memory.category == "allergy":
            profile["allergies"].append(value["name"])
        elif memory.category == "cuisine_preference":
            target = "liked_cuisines" if value.get("sentiment") == "likes" else "disliked_cuisines"
            profile[target].append(value["name"])
        elif memory.category == "budget":
            profile["budgets"].append(
                f"{value.get('context', 'meal')} up to {value.get('currency', 'USD')} {value['maximum']:g}"
            )
        elif memory.category == "merchant_preference" and value.get("sentiment") == "likes":
            profile["preferred_merchants"].append(value["name"])
    return profile


def regenerate_persona(db: Session, user_id: UUID) -> Persona:
    active = list(
        db.scalars(select(Memory).where(Memory.user_id == user_id, Memory.status == "active"))
    )
    profile = profile_from_memories(active)
    version = db.scalar(
        select(func.coalesce(func.max(Persona.version), 0)).where(Persona.user_id == user_id)
    )
    persona = Persona(
        user_id=user_id,
        version=int(version or 0) + 1,
        profile=profile,
        summary=generate_persona_summary(profile),
    )
    db.add(persona)
    db.flush()
    return persona


def evidence_for_memory(db: Session, memory_id: UUID) -> list[Message]:
    return list(
        db.scalars(
            select(Message)
            .join(MemorySource, MemorySource.message_id == Message.id)
            .where(MemorySource.memory_id == memory_id)
            .order_by(Message.created_at)
        )
    )
