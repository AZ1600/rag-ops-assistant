from fastapi.testclient import TestClient
import pytest

from src import api


@pytest.fixture
def failing_client(monkeypatch):
    class FailingAgent:
        async def start(self):
            pass

        async def close(self):
            pass

        async def ask(self, question):
            raise RuntimeError("Internal service credentials must not appear in responses")

    monkeypatch.setattr(api, "LangGraphAgentService", FailingAgent)
    with TestClient(api.app) as client:
        yield client


def test_internal_failure_returns_generic_error(failing_client):
    response = failing_client.post("/ask", json={"question": "dns"})
    assert response.status_code == 500
    assert response.json() == {"detail": "The agent failed to process the question."}


@pytest.mark.parametrize("body", [{}, {"question": None}, {"question": ["dns"]}])
def test_invalid_request_shape_is_rejected(failing_client, body):
    assert failing_client.post("/ask", json=body).status_code == 422
