import json
import re
from collections.abc import Sequence
from typing import Any

from openai import OpenAI

from .config import settings
from .models import Memory, Message
from .schemas import (
    MemoryCandidate,
    MemoryExtraction,
    PersonaSummaryOutput,
    SessionSummaryOutput,
)


def _openai_enabled() -> bool:
    return settings.llm_mode == "openai" and bool(settings.openai_api_key)


def _client() -> OpenAI:
    return OpenAI(api_key=settings.openai_api_key)


def generate_chat(
    messages: Sequence[Message], active_memories: Sequence[Memory], session_summary: str | None
) -> str:
    if not _openai_enabled():
        latest = messages[-1].content
        if active_memories:
            preferences = ", ".join(memory.description for memory in active_memories)
            return (
                f"Based on what I remember ({preferences}), I can personalize options for: {latest}"
            )
        return (
            "I can help with that. Tell me what food you like, your usual budget, and any "
            "dietary restrictions or allergies. I will only save durable preferences when you "
            "end the session."
        )

    context = {
        "session_summary": session_summary,
        "active_memories": [
            {"category": memory.category, "description": memory.description}
            for memory in active_memories
        ],
        "conversation": [
            {"role": message.role, "content": message.content} for message in messages[-20:]
        ],
    }
    response = _client().responses.create(
        model=settings.chat_model,
        instructions=(
            "You are a concise commerce assistant. Use active memories when relevant. Never "
            "claim that an allergen is safe; tell users to verify allergen handling. Do not "
            "invent restaurants, prices, or availability."
        ),
        input=json.dumps(context),
    )
    if not response.output_text:
        raise RuntimeError("The model returned no chat response.")
    return response.output_text


def summarize_session(
    previous_summary: str | None,
    previous_data: dict[str, Any] | None,
    messages: Sequence[Message],
) -> SessionSummaryOutput:
    if not _openai_enabled():
        user_text = " ".join(message.content for message in messages if message.role == "user")
        return SessionSummaryOutput(
            summary=(user_text[:500] or previous_summary or "No user messages yet."),
            current_goal=(messages[-1].content[:160] if messages else None),
            temporary_constraints=[],
            unresolved_questions=[],
            discussed_merchants=[],
            possible_memory_candidates=[],
        )

    payload = {
        "previous_summary": previous_summary,
        "previous_structured_summary": previous_data,
        "new_messages": [
            {"id": str(message.id), "role": message.role, "content": message.content}
            for message in messages
        ],
    }
    response = _client().responses.parse(
        model=settings.memory_model,
        input=[
            {
                "role": "system",
                "content": (
                    "Update the rolling session summary. Keep temporary requests separate from "
                    "possible durable preferences. Do not convert possibilities into facts."
                ),
            },
            {"role": "user", "content": json.dumps(payload)},
        ],
        text_format=SessionSummaryOutput,
    )
    if response.output_parsed is None:
        raise RuntimeError("The model returned no session summary.")
    return response.output_parsed


def extract_memories(messages: Sequence[Message]) -> MemoryExtraction:
    if not _openai_enabled():
        return MemoryExtraction(candidates=_demo_candidates(messages))

    transcript = [
        {"id": str(message.id), "role": message.role, "content": message.content}
        for message in messages
    ]
    response = _client().responses.parse(
        model=settings.memory_model,
        input=[
            {
                "role": "system",
                "content": (
                    "Extract durable user memories only from user messages. Allowed categories: "
                    "dietary_restriction, allergy, cuisine_preference, budget, and "
                    "merchant_preference. Allergies and dietary restrictions must be explicit. "
                    "Mark one-time, tonight-only, hypothetical, or other-person statements as "
                    "durable=false. Include exact supporting user message IDs. Use inferred only "
                    "for observed cuisine, budget, or merchant behavior that was not directly "
                    "stated as a preference."
                ),
            },
            {"role": "user", "content": json.dumps(transcript)},
        ],
        text_format=MemoryExtraction,
    )
    if response.output_parsed is None:
        raise RuntimeError("The model returned no memory extraction.")
    return response.output_parsed


def generate_persona_summary(profile: dict[str, Any]) -> str:
    if not _openai_enabled():
        parts: list[str] = []
        labels = {
            "dietary": "Dietary",
            "allergies": "Allergies",
            "liked_cuisines": "Likes",
            "disliked_cuisines": "Dislikes",
            "budgets": "Budgets",
            "preferred_merchants": "Merchants",
        }
        for key, label in labels.items():
            values = profile.get(key) or []
            if values:
                parts.append(f"{label}: {', '.join(str(value) for value in values)}")
        return ". ".join(parts) + ("." if parts else "No active durable memories yet.")

    response = _client().responses.parse(
        model=settings.memory_model,
        input=[
            {
                "role": "system",
                "content": "Write one factual sentence describing this customer profile.",
            },
            {"role": "user", "content": json.dumps(profile)},
        ],
        text_format=PersonaSummaryOutput,
    )
    if response.output_parsed is None:
        raise RuntimeError("The model returned no persona summary.")
    return response.output_parsed.summary


def _candidate(
    message: Message,
    category: str,
    value: str,
    description: str,
    *,
    source_type: str = "explicit",
    sentiment: str | None = None,
    amount: float | None = None,
    context: str | None = None,
) -> MemoryCandidate:
    return MemoryCandidate(
        category=category,
        normalized_value=value.strip().lower(),
        sentiment=sentiment,
        amount=amount,
        currency="USD" if amount is not None else None,
        context=context,
        description=description,
        source_type=source_type,
        evidence_message_ids=[message.id],
        durable=True,
        subject_is_user=True,
    )


def _demo_candidates(messages: Sequence[Message]) -> list[MemoryCandidate]:
    candidates: list[MemoryCandidate] = []
    diets = ("vegetarian", "vegan", "halal", "kosher", "gluten-free")
    cuisines = ("thai", "italian", "mexican", "indian", "chinese", "japanese", "greek")

    for message in messages:
        if message.role != "user":
            continue
        text = message.content.lower()
        if re.search(r"\b(my friend|my partner|my child|they are|he is|she is)\b", text):
            continue

        for diet in diets:
            if diet in text and re.search(r"\b(i am|i'm|i follow|my diet is)\b", text):
                candidates.append(
                    _candidate(
                        message,
                        "dietary_restriction",
                        diet,
                        f"Follows a {diet} diet",
                    )
                )

        allergy = re.search(r"\b(?:(?:i am|i'm) )?allergic to ([a-z -]{2,40})", text)
        if allergy:
            allergen = re.split(r"[,.]|\band\b", allergy.group(1))[0].strip()
            candidates.append(_candidate(message, "allergy", allergen, f"Allergic to {allergen}"))

        for cuisine in cuisines:
            if cuisine not in text:
                continue
            if re.search(rf"\b(i (?:love|like|prefer)|my favorite.*)\b.*\b{cuisine}\b", text):
                candidates.append(
                    _candidate(
                        message,
                        "cuisine_preference",
                        cuisine,
                        f"Likes {cuisine.title()} cuisine",
                        sentiment="likes",
                    )
                )
            elif re.search(rf"\b(i (?:dislike|hate|avoid))\b.*\b{cuisine}\b", text):
                candidates.append(
                    _candidate(
                        message,
                        "cuisine_preference",
                        cuisine,
                        f"Dislikes {cuisine.title()} cuisine",
                        sentiment="dislikes",
                    )
                )
            elif re.search(rf"\b(i (?:ordered|chose|got))\b.*\b{cuisine}\b", text):
                candidates.append(
                    _candidate(
                        message,
                        "cuisine_preference",
                        cuisine,
                        f"Often chooses {cuisine.title()} cuisine",
                        source_type="inferred",
                        sentiment="likes",
                    )
                )

        budget = re.search(r"\b(?:under|up to|less than|max(?:imum)?)\s*\$\s*(\d+(?:\.\d+)?)", text)
        if budget and re.search(r"\b(usually|normally|typically|budget)\b", text):
            amount = float(budget.group(1))
            candidates.append(
                _candidate(
                    message,
                    "budget",
                    str(amount),
                    f"Usually spends up to ${amount:g} per meal",
                    amount=amount,
                    context="meal",
                )
            )

        merchant = re.search(
            r"\b(?:i prefer|my favorite (?:restaurant|store) is)\s+([\w &'’-]{2,60})", text
        )
        if merchant:
            name = re.split(r"[,.]", merchant.group(1))[0].strip()
            candidates.append(
                _candidate(
                    message,
                    "merchant_preference",
                    name,
                    f"Prefers {name.title()}",
                    sentiment="likes",
                )
            )

    return candidates
