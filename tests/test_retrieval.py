import json

import numpy as np
import pytest

from src import rag_core


class FixedEmbedding:
    def __init__(self):
        self.calls = []

    def encode(self, query, normalize_embeddings):
        self.calls.append((query, normalize_embeddings))
        return np.array([1.0, 0.0])


class FixedReranker:
    def __init__(self, scores):
        self.scores = scores
        self.calls = []

    def predict(self, pairs):
        self.calls.append(pairs)
        return np.array(self.scores)


def chunk(number, text, source="operations.md"):
    return {"chunk_number": number, "source": source, "text": text}


@pytest.mark.parametrize("query,text,expected", [
    ("How does PRIVATE DNS work?", "Private DNS links", 2 / 3),
    ("DNS DNS", "dns", 1.0),
    ("the and how", "anything", 0.0),
    ("private-endpoint workload_id", "private-endpoint", 0.5),
    ("approval", "observability", 0.0),
])
def test_keyword_matching(query, text, expected):
    assert rag_core.keyword_score(query, text) == pytest.approx(expected)


def test_hybrid_ranking_combines_meaning_keywords_and_preserves_provenance():
    model = FixedEmbedding()
    chunks = [chunk(10, "unrelated", "semantic.md"),
              chunk(20, "private dns", "network.md")]
    results = rag_core.hybrid_search(
        "private dns", chunks, np.array([[0.8, 0.6], [0.7, 0.71414284]]), model,
    )
    # Keyword overlap lets the second chunk beat the higher semantic score.
    assert [item["chunk_number"] for item in results] == [20, 10]
    assert results[0]["source"] == "network.md"
    assert results[0]["text"] == "private dns"
    assert results[0]["hybrid_score"] == pytest.approx(0.775)
    assert results[0]["semantic_score"] == pytest.approx(0.7)
    assert results[0]["keyword_score"] == 1.0
    assert model.calls == [("private dns", True)]


def test_hybrid_threshold_includes_boundary_and_limits_candidates():
    records = [chunk(1, "dns"), chunk(2, "dns"), chunk(3, "dns")]
    embeddings = np.array([[1.0, 0], [0.0, 1], [-1.0, 0]])
    model = FixedEmbedding()
    results = rag_core.hybrid_search("dns", records, embeddings, model, min_score=0.25)
    assert [item["chunk_number"] for item in results] == [1, 2]
    limited = rag_core.hybrid_search(
        "dns", records, embeddings, model, candidate_count=1, min_score=0.25,
    )
    assert [item["chunk_number"] for item in limited] == [1]


def test_hybrid_rejects_unrelated_candidates():
    assert rag_core.hybrid_search(
        "dns", [chunk(1, "annual leave")], np.array([[0, 1.0]]), FixedEmbedding(),
    ) == []


def test_reranker_orders_filters_and_limits_with_source_metadata():
    candidates = [chunk(1, "one", "a.md"), chunk(2, "two", "b.md"),
                  chunk(3, "three", "c.md"), chunk(4, "four", "d.md")]
    reranker = FixedReranker([-1.0, 4.0, -1.01, 2.0])
    results = rag_core.rerank_results("question", candidates, reranker, top_n=2)
    assert [item["chunk_number"] for item in results] == [2, 4]
    assert [item["source"] for item in results] == ["b.md", "d.md"]
    assert [item["rerank_score"] for item in results] == [4.0, 2.0]
    assert reranker.calls == [[["question", text] for text in ("one", "two", "three", "four")]]


def test_reranker_includes_exact_threshold():
    assert rag_core.rerank_results("q", [chunk(1, "text")], FixedReranker([-1.0]))


def test_empty_candidates_skip_reranker():
    reranker = FixedReranker([])
    assert rag_core.rerank_results("q", [], reranker) == []
    assert reranker.calls == []


def test_context_keeps_chunk_numbers_sources_and_order():
    assert rag_core.build_context([chunk(7, "first", "a.md"), chunk(2, "second", "b.md")]) == (
        "[Chunk 7]\nSource: a.md\nfirst\n\n[Chunk 2]\nSource: b.md\nsecond"
    )
    assert rag_core.build_context([]) == ""


@pytest.mark.parametrize("missing", ["embeddings", "chunks"])
def test_missing_index_reports_ingestion_command(tmp_path, monkeypatch, missing):
    embeddings_file, chunks_file = tmp_path / "embeddings.npy", tmp_path / "chunks.json"
    monkeypatch.setattr(rag_core, "EMBEDDINGS_FILE", embeddings_file)
    monkeypatch.setattr(rag_core, "CHUNKS_FILE", chunks_file)
    if missing != "embeddings":
        np.save(embeddings_file, np.array([[1.0, 0]]))
    if missing != "chunks":
        chunks_file.write_text("{}")
    with pytest.raises(SystemExit, match="RAG index not found"):
        rag_core.load_index()


def test_load_index_reads_vectors_and_source_metadata(tmp_path, monkeypatch):
    vectors = np.array([[1.0, 0]])
    metadata = {"embedding_model": "fixture", "chunks": [chunk(1, "dns")]}
    np.save(tmp_path / "embeddings.npy", vectors)
    (tmp_path / "chunks.json").write_text(json.dumps(metadata))
    monkeypatch.setattr(rag_core, "EMBEDDINGS_FILE", tmp_path / "embeddings.npy")
    monkeypatch.setattr(rag_core, "CHUNKS_FILE", tmp_path / "chunks.json")
    actual_vectors, actual_metadata = rag_core.load_index()
    np.testing.assert_array_equal(actual_vectors, vectors)
    assert actual_metadata == metadata
