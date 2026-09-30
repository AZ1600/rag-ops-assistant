import pytest
from fastapi.testclient import TestClient

import src.api as api


class FakeAgentService:
    """
    Fake replacement for LangGraphAgentService.

    It lets us test the FastAPI layer without calling
    Bedrock, MCP, or the real RAG pipeline.
    """

    async def start(self):
        pass

    async def close(self):
        pass

    async def ask(self, question: str) -> dict:
        if question == "How does the VM securely access Blob Storage?":
            return {
                "answer": (
                    "The VM securely accesses Blob Storage "
                    "using managed identity and private networking."
                ),
                "sources": [
                    "az104-infrastructure-lab.md"
                ],
                "evidence": [
                    {
                        "chunk_number": 15,
                        "source": "az104-infrastructure-lab.md",
                        "rerank_score": 6.02,
                        "hybrid_score": 0.58,
                    }
                ],
            }

        if question == "What is the company annual leave policy?":
            return {
                "answer": (
                    "The knowledge base does not contain "
                    "sufficient information to answer that question."
                ),
                "sources": [],
                "evidence": [],
            }

        return {
            "answer": "Hello! How can I assist you today?",
            "sources": [],
            "evidence": [],
        }


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        api,
        "LangGraphAgentService",
        FakeAgentService,
    )

    with TestClient(api.app) as test_client:
        yield test_client


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200

    assert response.json() == {
        "status": "ok",
        "service": "rag-ops-assistant",
    }


def test_known_knowledge_base_question(client):
    response = client.post(
        "/ask",
        json={
            "question": (
                "How does the VM securely access Blob Storage?"
            )
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["sources"] == [
        "az104-infrastructure-lab.md"
    ]

    assert len(body["evidence"]) == 1

    assert body["evidence"][0]["chunk_number"] == 15


def test_no_evidence_question(client):
    response = client.post(
        "/ask",
        json={
            "question": (
                "What is the company annual leave policy?"
            )
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["answer"] == (
        "The knowledge base does not contain "
        "sufficient information to answer that question."
    )

    assert body["sources"] == []
    assert body["evidence"] == []


def test_general_question(client):
    response = client.post(
        "/ask",
        json={
            "question": "Say hello in one sentence."
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["answer"] == (
        "Hello! How can I assist you today?"
    )

    assert body["sources"] == []
    assert body["evidence"] == []


def test_empty_question_returns_400(client):
    response = client.post(
        "/ask",
        json={
            "question": "   "
        },
    )

    assert response.status_code == 400

    assert response.json() == {
        "detail": "Question cannot be empty."
    }
