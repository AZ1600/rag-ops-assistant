import numpy as np
import pytest

from src import rag_core


class SequencedReranker:
    def __init__(self, scores):
        self.scores = iter(scores)
        self.calls = []

    def predict(self, pairs):
        self.calls.append(pairs)
        return np.array(next(self.scores))


def records():
    return [{"chunk_number": 7, "source": "ops.md", "text": "No traffic is not a failure."}]


@pytest.mark.parametrize("question,expected", [
    ("Will a quiet service fail?", "Will an idle application fail?"),
    ("Does a\nquiet application fail?", "Does an idle application fail?"),
    ("Are QUIET SERVICES failing?", "Are idle applications failing?"),
    ("How does the quiet app behave?", "How does the idle application behave?"),
    ("What is a quiet period?", "What is a quiet period?"),
    ("A quiet serviceworker", "A quiet serviceworker"),
    ("A nonquiet service", "A nonquiet service"),
])
def test_alias_is_a_bounded_phrase_and_leaves_other_terms_untouched(question, expected):
    assert rag_core.rerank_query_alias(question) == expected


def test_retry_keeps_source_text_and_records_the_query_used_for_its_score():
    question = "Will a quiet service fail?"
    reranker = SequencedReranker([[-9], [2]])
    result = rag_core.rerank_results(question, records(), reranker)
    assert reranker.calls == [[[question, records()[0]["text"]]],
                              [["Will an idle application fail?", records()[0]["text"]]]]
    assert result[0]["chunk_number"] == 7
    assert result[0]["source"] == "ops.md"
    assert result[0]["text"] == records()[0]["text"]
    assert result[0]["rerank_score"] == 2
    assert result[0]["rerank_query"] == "Will an idle application fail?"


def test_original_evidence_is_returned_without_retrying_or_changing_its_score():
    reranker = SequencedReranker([[1]])
    result = rag_core.rerank_results("Will a quiet service fail?", records(), reranker)
    assert len(reranker.calls) == 1
    assert result[0]["rerank_score"] == 1
    assert "rerank_query" not in result[0]


@pytest.mark.parametrize("score,expected", [(-1.0, True), (-1.001, False)])
def test_retry_has_the_same_rejection_boundary(score, expected):
    reranker = SequencedReranker([[-9], [score]])
    assert bool(rag_core.rerank_results("Will a quiet service fail?", records(), reranker)) is expected
    assert len(reranker.calls) == 2


def test_retry_sorts_and_limits_results_without_adding_chunks():
    chunks = [dict(records()[0], chunk_number=n) for n in [1, 2, 3]]
    reranker = SequencedReranker([[-9, -9, -9], [0, 3, 1]])
    result = rag_core.rerank_results("Will a quiet service fail?", chunks, reranker, top_n=2)
    assert [r["chunk_number"] for r in result] == [2, 3]
    assert all(len(call) == 3 for call in reranker.calls)


@pytest.mark.parametrize("question", [
    "What is the tenant ID for a quiet service?",
    "How many days are logs for a quiet service retained?",
])
def test_alias_cannot_bypass_original_literal_value_guards(question):
    reranker = SequencedReranker([])
    assert rag_core.rerank_results(question, records(), reranker) == []
    assert reranker.calls == []


def test_no_retry_for_other_questions_or_empty_candidates():
    reranker = SequencedReranker([[-9]])
    assert rag_core.rerank_results("Where are the logs?", records(), reranker) == []
    assert len(reranker.calls) == 1
    assert rag_core.rerank_results("Will a quiet service fail?", [], reranker) == []
    assert len(reranker.calls) == 1


def test_retry_model_errors_propagate_instead_of_becoming_no_evidence():
    class FailingRetry:
        calls = 0
        def predict(self, pairs):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("reranker unavailable")
            return np.array([-9.0] * len(pairs))
    with pytest.raises(RuntimeError, match="reranker unavailable"):
        rag_core.rerank_results("Will a quiet service fail?", records(), FailingRetry())
