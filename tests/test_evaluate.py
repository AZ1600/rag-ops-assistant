import json
import hashlib
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
        "source_coverage": passed if not expect_evidence or not results else set(expected_sources).issubset({r["source"] for r in results}),
        "evidence_coverage": passed if not expect_evidence or not results else True,
    }


@pytest.mark.parametrize("expected_source,expected_exit", [("network.md", 0), ("wrong.md", 1)])
@pytest.mark.parametrize("custom_cases", [False, True])
@pytest.mark.parametrize("alias_retry", [False, True])
def test_module_cli_exits_nonzero_for_failed_retrieval_cases(
    tmp_path, monkeypatch, capsys, expected_source, expected_exit, custom_cases, alias_retry,
):
    (tmp_path / "evals").mkdir()
    (tmp_path / "data").mkdir()
    documents = {"network.md": "private dns", "wrong.md": "an unrelated topic"}
    for name, text in documents.items():
        (tmp_path / "data" / name).write_text(text)
    dataset = tmp_path / ("evals/probes.json" if custom_cases else "evals/retrieval_cases.json")
    question = "How does a quiet service resolve private DNS?" if alias_retry else "dns"
    dataset.write_text(json.dumps([
        {"id": "cli-case", "category": "supported", "question": question, "expect_evidence": True,
         "expected_sources": [expected_source], "rationale": "Check module exit status.",
         "reference_evidence": [{"source": expected_source, "quote": documents[expected_source]}]},
    ]))
    (tmp_path / "index").mkdir()
    np.save(tmp_path / "index/embeddings.npy", np.array([[1.0, 0], [0, 1.0]]))
    (tmp_path / "index/chunks.json").write_text(json.dumps({
        "embedding_model": "fixture", "chunking_version": rag_core.CHUNKING_VERSION, "chunks": [
            {"chunk_number": number, "source": name, "text": text}
            for number, (name, text) in enumerate(documents.items(), start=1)
        ],
    }))
    monkeypatch.chdir(tmp_path)

    class Embedding:
        def encode(self, query, normalize_embeddings):
            return np.array([1.0, 0])

    class Reranker:
        def predict(self, pairs):
            return np.array([-9.0 if "quiet service" in query else 3.0 for query, text in pairs])

    model_options = []

    def embedding_factory(name, **kwargs):
        model_options.append(kwargs)
        return Embedding()

    def reranker_factory(name, **kwargs):
        model_options.append(kwargs)
        return Reranker()

    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", embedding_factory)
    monkeypatch.setattr(sentence_transformers, "CrossEncoder", reranker_factory)
    argv = ["evaluate", "--offline", "--report", "eval-results/report.json"]
    if custom_cases:
        # The default file is deliberately absent: --cases must control loading
        # and the fingerprint rather than silently using the primary dataset.
        argv.extend(["--cases", str(dataset)])
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.delitem(sys.modules, "src.evaluate", raising=False)
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("src.evaluate", run_name="__main__", alter_sys=True)
    assert exc.value.code == expected_exit
    output = capsys.readouterr().out
    assert f"Passed: {1 - expected_exit}/1" in output
    assert ("[PASS]" if expected_exit == 0 else "[FAIL]") in output
    report = json.loads((tmp_path / "eval-results/report.json").read_text())
    assert report["summary"] == {"passed": 1 - expected_exit, "total": 1,
                                 "categories": {"supported": {"passed": 1 - expected_exit, "total": 1}},
                                 "reference_coverage": {"covered": 1 - expected_exit, "total": 1}}
    assert report["cases"][0]["metrics"]["passed"] == (expected_exit == 0)
    assert report["cases"][0]["results"][0]["source"] == "network.md"
    assert report["cases"][0]["question"] == question
    if alias_retry:
        assert report["cases"][0]["results"][0]["rerank_query"] == "How does an idle application resolve private DNS?"
    else:
        assert "rerank_query" not in report["cases"][0]["results"][0]
    assert set(report["corpus_sha256"]) == set(documents)
    assert report["dataset_sha256"] == hashlib.sha256(dataset.read_bytes()).hexdigest()
    assert report["retrieval_policy"] == {
        "chunking": rag_core.CHUNKING_VERSION, "grounding": rag_core.GROUNDING_VERSION,
        "reranking": rag_core.RERANKING_VERSION,
    }
    assert model_options == [{"local_files_only": True}, {"local_files_only": True}]


def test_empty_evaluation_suite_is_rejected_before_loading_models(tmp_path, monkeypatch):
    from src import evaluate

    cases = tmp_path / "empty.json"
    cases.write_text("[]")
    monkeypatch.setattr(evaluate, "EVAL_FILE", cases)

    def unexpected_index_load():
        pytest.fail("Empty evaluation must fail before loading an index or models")

    monkeypatch.setattr(evaluate, "load_index", unexpected_index_load)
    with pytest.raises(ValueError, match="at least one case"):
        evaluate.main([])


@pytest.mark.parametrize("results,covered", [
    ([{"source": "a.md", "text": "wrong content"}], False),
    ([{"source": "b.md", "text": "first fact second fact"}], False),
    ([{"source": "a.md", "text": "first fact"}], False),
    ([{"source": "a.md", "text": "first fact"}, {"source": "a.md", "text": "second fact"}], True),
    ([{"source": "a.md", "text": "first\n fact and second\t fact"}], True),
])
def test_reference_coverage_is_diagnostic_and_checks_the_correct_source(results, covered):
    from src.evaluate import evaluate_case

    evaluation = evaluate_case({
        "expect_evidence": True, "expected_sources": ["a.md"],
        "reference_evidence": [{"source": "a.md", "quote": "first fact"},
                               {"source": "a.md", "quote": "second fact"}],
    }, results)
    assert evaluation["evidence_coverage"] == covered
    assert evaluation["passed"] == all(result["source"] == "a.md" for result in results)


def test_cross_project_case_requires_reference_evidence_from_both_sources():
    from src.evaluate import evaluate_case

    case = {"expect_evidence": True, "expected_sources": ["a.md", "b.md"],
            "reference_evidence": [{"source": "a.md", "quote": "export"},
                                   {"source": "b.md", "quote": "approval"}]}
    first = [{"source": "a.md", "text": "export"}]
    assert evaluate_case(case, first)["passed"] is False
    assert evaluate_case(case, first + [{"source": "b.md", "text": "approval"}])["passed"] is True


def test_stale_index_is_rejected_before_loading_models(monkeypatch):
    from src import evaluate, ingest

    monkeypatch.setattr(evaluate, "load_eval_cases", lambda: [{"id": "case"}])
    monkeypatch.setattr(evaluate, "load_index", lambda: (np.array([[1.0, 0]]), {"chunks": []}))
    monkeypatch.setattr(ingest, "load_all_documents", lambda: [{"source": "a.md", "text": "changed"}])
    with pytest.raises(ValueError, match="index is stale"):
        evaluate.main(["--offline"])
