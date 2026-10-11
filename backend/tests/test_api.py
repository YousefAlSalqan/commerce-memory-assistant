from uuid import UUID

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Memory, MemorySource


def create_user(client):
    response = client.post("/api/users", json={"display_name": "Yousef"})
    assert response.status_code == 201
    return response.json()


def test_full_memory_flow_and_physical_delete(client):
    user = create_user(client)
    first = client.post(f"/api/users/{user['id']}/sessions").json()
    prompt = (
        "I'm vegetarian, allergic to peanuts, I usually spend under $25 per meal, "
        "and I love Thai food."
    )
    assert (
        client.post(f"/api/sessions/{first['id']}/messages", json={"content": prompt}).status_code
        == 200
    )
    ended = client.post(f"/api/sessions/{first['id']}/end")
    assert ended.status_code == 200

    memories = client.get(f"/api/users/{user['id']}/memories").json()
    categories = {memory["category"] for memory in memories if memory["status"] == "active"}
    assert categories == {"dietary_restriction", "allergy", "budget", "cuisine_preference"}
    assert all(memory["evidence"] for memory in memories)

    second = client.post(f"/api/users/{user['id']}/sessions").json()
    reply = client.post(
        f"/api/sessions/{second['id']}/messages",
        json={"content": "What should I order tonight?"},
    ).json()
    assert len(reply["memories_used"]) == 4
    assert "vegetarian" in reply["message"]["content"].lower()

    target = memories[0]
    assert client.delete(f"/api/memories/{target['id']}").status_code == 204
    remaining = client.get(f"/api/users/{user['id']}/memories").json()
    assert target["id"] not in {memory["id"] for memory in remaining}
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(MemorySource)
                .where(MemorySource.memory_id == UUID(target["id"]))
            )
            == 0
        )


def test_confirm_and_correct_memory(client):
    user = create_user(client)
    first = client.post(f"/api/users/{user['id']}/sessions").json()
    client.post(
        f"/api/sessions/{first['id']}/messages",
        json={"content": "I ordered Thai food"},
    )
    client.post(f"/api/sessions/{first['id']}/end")
    candidate = client.get(f"/api/users/{user['id']}/memories").json()[0]
    assert candidate["status"] == "candidate"

    confirmed = client.post(f"/api/memories/{candidate['id']}/confirm").json()
    assert confirmed["status"] == "active"
    assert confirmed["source_type"] == "explicit"
    assert confirmed["confidence"] == 1.0

    corrected = client.patch(
        f"/api/memories/{candidate['id']}",
        json={
            "value": {"name": "indian", "sentiment": "likes"},
            "description": "Likes Indian cuisine",
        },
    ).json()
    assert corrected["id"] != candidate["id"]
    assert corrected["description"] == "Likes Indian cuisine"
    with SessionLocal() as db:
        assert db.get(Memory, UUID(candidate["id"])).status == "superseded"


def test_summary_checkpoint_after_ten_user_messages(client):
    user = create_user(client)
    conversation = client.post(f"/api/users/{user['id']}/sessions").json()
    for index in range(10):
        response = client.post(
            f"/api/sessions/{conversation['id']}/messages",
            json={"content": f"Message {index}"},
        )
        assert response.status_code == 200

    updated = client.get(f"/api/sessions/{conversation['id']}").json()
    assert updated["summary_through_message_id"] is not None
    assert updated["summary"] is not None


def test_memory_disabled_prevents_extraction(client):
    user = create_user(client)
    client.patch(f"/api/users/{user['id']}", json={"memory_enabled": False})
    conversation = client.post(f"/api/users/{user['id']}/sessions").json()
    client.post(
        f"/api/sessions/{conversation['id']}/messages",
        json={"content": "I am vegetarian"},
    )
    client.post(f"/api/sessions/{conversation['id']}/end")
    assert client.get(f"/api/users/{user['id']}/memories").json() == []
