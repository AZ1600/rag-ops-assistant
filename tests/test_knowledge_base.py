import numpy as np
import pytest

from src import tools


@pytest.fixture
def knowledge_base(monkeypatch):
    records = [
        {"chunk_number": 1, "source": "network.md", "text": "private dns"},
        {"chunk_number": 2, "source": "network.md", "text": "dns zone"},
        {"chunk_number": 3, "source": "identity.md", "text": "managed identity"},
    ]
    vectors = np.array([[1.0, 0], [0.8, 0.6], [0.6, 0.8]])
    calls = {"encode": [], "predict": []}

    class Embedding:
        def encode(self, question, normalize_embeddings):
            calls["encode"].append((question, normalize_embeddings))
            return np.array([1.0, 0])

    class Reranker:
        def predict(self, pairs):
            calls["predict"].append(pairs)
            return np.array([4.0, 2.0, 3.0])

    monkeypatch.setattr(tools, "load_index", lambda: (
        vectors, {"embedding_model": "fixture", "chunks": records},
    ))
    monkeypatch.setattr(tools, "SentenceTransformer", lambda name: Embedding())
    monkeypatch.setattr(tools, "CrossEncoder", lambda name: Reranker())
    return tools.KnowledgeBaseTool(), calls


def test_search_runs_ranking_and_returns_matching_context_sources_evidence(knowledge_base):
    tool, calls = knowledge_base
    result = tool.search("  dns  ")
    assert result["found"] is True
    assert result["sources"] == ["network.md", "identity.md"]
    assert [item["chunk_number"] for item in result["evidence"]] == [1, 3, 2]
    assert [item["rerank_score"] for item in result["evidence"]] == [4.0, 3.0, 2.0]
    assert result["evidence"][1]["hybrid_score"] == pytest.approx(0.45)
    assert result["context"] == (
        "[Chunk 1]\nSource: network.md\nprivate dns\n\n"
        "[Chunk 3]\nSource: identity.md\nmanaged identity\n\n"
        "[Chunk 2]\nSource: network.md\ndns zone"
    )
    assert calls["encode"] == [("dns", True)]
    assert len(calls["predict"]) == 1


def test_blank_search_skips_models(knowledge_base):
    tool, calls = knowledge_base
    result = tool.search(" \n ")
    assert result["found"] is False
    assert result["context"] == ""
    assert result["sources"] == result["evidence"] == []
    assert calls == {"encode": [], "predict": []}


def test_search_rejects_semantic_mismatches_before_reranking(knowledge_base):
    tool, calls = knowledge_base
    tool.embeddings = np.array([[-1.0, 0]] * 3)
    result = tool.search("annual leave")
    assert result["found"] is False
    assert result["sources"] == result["evidence"] == []
    assert result["context"] == ""
    assert calls["predict"] == []


def test_search_refuses_when_reranker_rejects_all_candidates(knowledge_base, monkeypatch):
    tool, calls = knowledge_base
    monkeypatch.setattr(tool.reranker, "predict", lambda pairs: np.array([-2.0] * len(pairs)))
    result = tool.search("dns")
    assert result["found"] is False
    assert "reranking" in result["message"]
    assert result["sources"] == result["evidence"] == []
    assert result["context"] == ""
    assert len(calls["encode"]) == 1


def test_tool_refuses_unsupported_identifier_without_passing_background_as_evidence(knowledge_base):
    tool, calls = knowledge_base
    result = tool.search("What is the configured tenant ID?")
    assert result["found"] is False
    assert result["sources"] == result["evidence"] == []
    assert result["context"] == ""
    assert calls["predict"] == []


def test_tool_retries_only_reranking_and_returns_original_evidence(knowledge_base, monkeypatch):
    tool, calls = knowledge_base
    def predict(pairs):
        calls["predict"].append(pairs)
        if len(calls["predict"]) == 1:
            return np.array([-9.0] * len(pairs))
        return np.array([2.0] + [-9.0] * (len(pairs) - 1))
    monkeypatch.setattr(tool.reranker, "predict", predict)
    question = "How does a quiet service resolve private DNS?"
    result = tool.search(question)
    assert result["found"] is True
    assert result["sources"] == ["network.md"]
    assert result["context"] == "[Chunk 1]\nSource: network.md\nprivate dns"
    assert result["evidence"][0]["rerank_score"] == 2.0
    assert calls["encode"] == [(question, True)]
    assert len(calls["predict"]) == 2
    assert calls["predict"][1][0] == ["How does an idle application resolve private DNS?", "private dns"]
