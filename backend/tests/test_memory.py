from sqlalchemy.orm import Session

from app.database import engine
from app.memory import apply_candidates
from app.models import ConversationSession, Message, User
from app.schemas import MemoryCandidate


def candidate(message, category, value, source_type="explicit"):
    return MemoryCandidate(
        category=category,
        normalized_value=value,
        sentiment="likes" if category == "cuisine_preference" else None,
        amount=None,
        currency=None,
        context=None,
        description=f"Test {value}",
        source_type=source_type,
        evidence_message_ids=[message.id],
        durable=True,
        subject_is_user=True,
    )


def add_session(db, user, text):
    conversation = ConversationSession(user_id=user.id, status="closed")
    db.add(conversation)
    db.flush()
    message = Message(session_id=conversation.id, role="user", content=text)
    db.add(message)
    db.flush()
    db.refresh(conversation)
    return conversation, message


def test_explicit_allergy_is_active_but_inferred_allergy_is_rejected():
    with Session(engine, expire_on_commit=False) as db:
        user = User(display_name="Yousef")
        db.add(user)
        db.flush()
        conversation, message = add_session(db, user, "I am allergic to peanuts")

        explicit = apply_candidates(
            db, user, conversation, [candidate(message, "allergy", "peanuts")]
        )
        inferred = apply_candidates(
            db,
            user,
            conversation,
            [candidate(message, "allergy", "shellfish", "inferred")],
        )

        assert len(explicit) == 1
        assert explicit[0].status == "active"
        assert float(explicit[0].confidence) == 1.0
        assert inferred == []


def test_inferred_cuisine_activates_only_after_two_sessions():
    with Session(engine, expire_on_commit=False) as db:
        user = User(display_name="Yousef")
        db.add(user)
        db.flush()
        first_session, first_message = add_session(db, user, "I ordered Thai food")
        first = apply_candidates(
            db,
            user,
            first_session,
            [candidate(first_message, "cuisine_preference", "thai", "inferred")],
        )[0]
        db.commit()

        assert first.status == "candidate"
        assert float(first.confidence) == 0.5

        second_session, second_message = add_session(db, user, "I ordered Thai again")
        second = apply_candidates(
            db,
            user,
            second_session,
            [candidate(second_message, "cuisine_preference", "thai", "inferred")],
        )[0]

        assert second.id == first.id
        assert second.status == "active"
        assert float(second.confidence) == 0.7

        third_session, third_message = add_session(db, user, "I ordered Thai once more")
        third = apply_candidates(
            db,
            user,
            third_session,
            [candidate(third_message, "cuisine_preference", "thai", "inferred")],
        )[0]
        assert third.id == first.id
        assert float(third.confidence) == 0.8


def test_inferred_evidence_never_weakens_an_explicit_memory():
    with Session(engine, expire_on_commit=False) as db:
        user = User(display_name="Yousef")
        db.add(user)
        db.flush()
        first_session, first_message = add_session(db, user, "I love Thai food")
        explicit = apply_candidates(
            db,
            user,
            first_session,
            [candidate(first_message, "cuisine_preference", "thai")],
        )[0]
        db.commit()

        second_session, second_message = add_session(db, user, "I ordered Thai")
        reinforced = apply_candidates(
            db,
            user,
            second_session,
            [candidate(second_message, "cuisine_preference", "thai", "inferred")],
        )[0]

        assert reinforced.id == explicit.id
        assert reinforced.source_type == "explicit"
        assert reinforced.status == "active"
        assert float(reinforced.confidence) == 1.0


def test_memory_disabled_user_stores_nothing():
    with Session(engine, expire_on_commit=False) as db:
        user = User(display_name="Yousef", memory_enabled=False)
        db.add(user)
        db.flush()
        conversation, message = add_session(db, user, "I am vegetarian")
        result = apply_candidates(
            db,
            user,
            conversation,
            [candidate(message, "dietary_restriction", "vegetarian")],
        )
        assert result == []


def test_temporary_or_other_person_candidate_is_rejected():
    with Session(engine, expire_on_commit=False) as db:
        user = User(display_name="Yousef")
        db.add(user)
        db.flush()
        conversation, message = add_session(db, user, "My friend wants Thai tonight")
        temporary = candidate(message, "cuisine_preference", "thai")
        temporary.durable = False
        other_person = candidate(message, "cuisine_preference", "thai")
        other_person.subject_is_user = False
        assert apply_candidates(db, user, conversation, [temporary, other_person]) == []
