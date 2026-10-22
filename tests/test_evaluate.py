import json
import runpy
import sys

import numpy as np
import pytest
import sentence_transformers

from src import rag_core


@pytest.mark.parametrize("expect_evidence,expected_sources,results,passed,top1,purity", [
    (False, [], [], True, True, True),
    (False, [], [{"source": "a.md"}], False, False, False),
    (True, ["a.md"], [], False, False, False),
    (True, ["a.md"], [{"source": "a.md"}], True, True, True),
    (True, ["a.md"], [{"source": "b.md"}], False, False, False),
    (True, ["a.md"], [{"source": "a.md"}, {"source": "b.md"}], False, True, False),
    (True, ["a.md", "b.md"], [{"source": "b.md"}, {"source": "a.md"}], True, True, True),
])
def test_evaluation_metrics(expect_evidence, expected_sources, results, passed, top1, purity):
    # Import inside the test so the original module-import regression is reported here.
    from src.evaluate import evaluate_case

    assert evaluate_case({"expect_evidence": expect_evidence, "expected_sources": expected_sources}, results) == {
        "passed": passed, "top1_correct": top1, "source_purity": purity,
    }


@pytest.mark.parametrize("expected_source,expected_exit", [("network.md", 0), ("wrong.md", 1)])
def test_module_cli_exits_nonzero_for_failed_retrieval_cases(
    tmp_path, monkeypatch, capsys, expected_source, expected_exit,
):
    (tmp_path / "evals").mkdir()
    (tmp_path / "evals/retrieval_cases.json").write_text(json.dumps([
        {"question": "dns", "expect_evidence": True, "expected_sources": [expected_source]},
    ]))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(rag_core, "load_index", lambda: (
        np.array([[1.0, 0]]), {"embedding_model": "fixture", "chunks": [
            {"chunk_number": 1, "source": "network.md", "text": "private dns"},
        ]},
    ))

    class Embedding:
        def encode(self, query, normalize_embeddings):
            return np.array([1.0, 0])

    class Reranker:
        def predict(self, pairs):
            return np.array([3.0] * len(pairs))

    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", lambda name: Embedding())
    monkeypatch.setattr(sentence_transformers, "CrossEncoder", lambda name: Reranker())
    monkeypatch.delitem(sys.modules, "src.evaluate", raising=False)
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("src.evaluate", run_name="__main__", alter_sys=True)
    assert exc.value.code == expected_exit
    output = capsys.readouterr().out
    assert f"Passed: {1 - expected_exit}/1" in output
    assert ("[PASS]" if expected_exit == 0 else "[FAIL]") in output


def test_empty_evaluation_suite_is_rejected_before_loading_models(tmp_path, monkeypatch):
    from src import evaluate

    cases = tmp_path / "empty.json"
    cases.write_text("[]")
    monkeypatch.setattr(evaluate, "EVAL_FILE", cases)

    def unexpected_index_load():
        pytest.fail("Empty evaluation must fail before loading an index or models")

    monkeypatch.setattr(evaluate, "load_index", unexpected_index_load)
    with pytest.raises(ValueError, match="at least one case"):
        evaluate.main()
