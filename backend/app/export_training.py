import hashlib
import json

from sqlalchemy import select

from .database import SessionLocal
from .models import ConversationSession, Memory, User


def main() -> None:
    with SessionLocal() as db:
        users = db.scalars(select(User).where(User.memory_enabled.is_(True)))
        for user in users:
            anonymous_id = hashlib.sha256(str(user.id).encode()).hexdigest()[:16]
            sessions = db.scalars(
                select(ConversationSession).where(
                    ConversationSession.user_id == user.id,
                    ConversationSession.status == "closed",
                )
            )
            memories = list(
                db.scalars(
                    select(Memory).where(
                        Memory.user_id == user.id,
                        Memory.status == "active",
                    )
                )
            )
            for conversation in sessions:
                print(
                    json.dumps(
                        {
                            "anonymous_user_id": anonymous_id,
                            "session_summary": conversation.summary,
                            "accepted_memories": [
                                {
                                    "category": memory.category,
                                    "value": memory.value,
                                    "source_type": memory.source_type,
                                }
                                for memory in memories
                            ],
                        }
                    )
                )


if __name__ == "__main__":
    main()
