from fastapi.testclient import TestClient
from orgos.api import app


def test_agent_card_has_required_fields():
    client = TestClient(app)
    r = client.get("/agent-card.json")
    assert r.status_code == 200
    card = r.json()
    assert card["name"] == "orgos-engineering"
    assert "skills" in card and len(card["skills"]) >= 5
    for s in card["skills"]:
        assert "id" in s and "name" in s and "description" in s
