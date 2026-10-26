from pathlib import Path
import argparse
import hashlib
from importlib.metadata import version
import json
import platform

from sentence_transformers import CrossEncoder, SentenceTransformer

from src.eval_cases import validate_eval_cases
from src.rag_core import (
    CHUNKS_FILE,
    EMBEDDINGS_FILE,
    DEFAULT_CANDIDATE_COUNT,
    DEFAULT_HYBRID_MIN_SCORE,
    DEFAULT_TOP_N,
    DEFAULT_RERANK_MIN_SCORE,
    RERANKER_MODEL,
    hybrid_search,
    load_index,
    rerank_results,
)


EVAL_FILE = Path("evals/retrieval_cases.json")
DATA_DIR = Path("data")


def load_documents():
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(DATA_DIR.glob("*.md"))}


def load_eval_cases():
    with EVAL_FILE.open(
        "r",
        encoding="utf-8",
    ) as file:
        return validate_eval_cases(json.load(file), load_documents())


def evaluate_case(
    case: dict,
    results: list[dict],
) -> dict:
    expect_evidence = case["expect_evidence"]

    if not expect_evidence:
        passed = len(results) == 0

        return {
            "passed": passed,
            "top1_correct": passed,
            "source_purity": passed,
            "source_coverage": passed,
            "evidence_coverage": passed,
        }

    if not results:
        return {
            "passed": False,
            "top1_correct": False,
            "source_purity": False,
            "source_coverage": False,
            "evidence_coverage": False,
        }

    expected_sources = set(
        case["expected_sources"]
    )

    top1_source = results[0]["source"]

    top1_correct = (
        top1_source in expected_sources
    )

    source_purity = all(
        result["source"] in expected_sources
        for result in results
    )
    source_coverage = expected_sources.issubset({result["source"] for result in results})

    # Report exact reference coverage separately: equivalent passages elsewhere
    # in the same document can still support an answer without matching this quote.
    evidence_coverage = all(
        any(
            result["source"] == reference["source"]
            and " ".join(reference["quote"].split()) in " ".join(result.get("text", "").split())
            for result in results
        )
        for reference in case.get("reference_evidence", [])
    )

    passed = (
        top1_correct
        and source_purity
        and source_coverage
    )

    return {
        "passed": passed,
        "top1_correct": top1_correct,
        "source_purity": source_purity,
        "source_coverage": source_coverage,
        "evidence_coverage": evidence_coverage,
    }


def build_summary(evaluations):
    summary = {"passed": 0, "total": len(evaluations), "categories": {},
               "reference_coverage": {"covered": 0, "total": 0}}
    for item in evaluations:
        category = item["category"]
        counts = summary["categories"].setdefault(category, {"passed": 0, "total": 0})
        counts["total"] += 1
        counts["passed"] += int(item["metrics"]["passed"])
        summary["passed"] += int(item["metrics"]["passed"])
        if category != "unsupported":
            summary["reference_coverage"]["total"] += 1
            summary["reference_coverage"]["covered"] += int(item["metrics"]["evidence_coverage"])
    return summary


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate retrieval against labelled document evidence.")
    parser.add_argument("--offline", action="store_true", help="Load cached models only; never download models.")
    parser.add_argument("--report", type=Path, help="Write a JSON report, including failed cases.")
    args = parser.parse_args(argv)
    cases = load_eval_cases()

    print("Loading RAG index...")

    embeddings, metadata = load_index()

    # Refuse a stale index rather than scoring today's labels against old content.
    from src import ingest

    current_chunks = ingest.load_all_documents()
    for number, record in enumerate(current_chunks, start=1):
        record["chunk_number"] = number
    if metadata["chunks"] != current_chunks:
        raise ValueError("The index is stale. Rebuild it with: python -m src.ingest")

    chunk_records = metadata["chunks"]
    model_name = metadata["embedding_model"]

    print("Loading embedding model...")
    model_options = {"local_files_only": True} if args.offline else {}
    model = SentenceTransformer(model_name, **model_options)

    print("Loading reranker...")
    reranker = CrossEncoder(RERANKER_MODEL, **model_options)

    passed = 0
    evaluations = []

    print("\n--- RETRIEVAL EVALUATION ---")

    for number, case in enumerate(
        cases,
        start=1,
    ):
        query = case["question"]

        candidates = hybrid_search(
            query=query,
            chunk_records=chunk_records,
            embeddings=embeddings,
            model=model,
        )

        results = rerank_results(
            query=query,
            candidates=candidates,
            reranker=reranker,
        )

        evaluation = evaluate_case(
            case,
            results,
        )
        evaluations.append({
            "id": case["id"],
            "category": case["category"],
            "question": query,
            "expected_sources": case["expected_sources"],
            "metrics": evaluation,
            "results": [{key: result[key] for key in (
                "chunk_number", "source", "hybrid_score", "rerank_score",
            )} for result in results],
        })

        success = evaluation["passed"]

        if success:
            passed += 1

        returned_sources = [
            result["source"]
            for result in results
        ]

        status = "PASS" if success else "FAIL"

        print(f"\n[{status}] Case {number}")
        print(f"Question: {query}")
        print(
            f"Expected: "
            f"{case['expected_sources']}"
        )
        print(
            f"Returned: "
            f"{returned_sources}"
        )
        print(
            f"Top-1 correct: "
            f"{evaluation['top1_correct']}"
        )
        print(
            f"Source purity: "
            f"{evaluation['source_purity']}"
        )
        print(f"Reference evidence covered: {evaluation['evidence_coverage']}")

    total = len(cases)

    print("\n--- SUMMARY ---")
    print(f"Passed: {passed}/{total}")
    print(f"Source-selection / abstention pass rate: {passed / total:.1%}")

    summary = build_summary(evaluations)
    for category, counts in sorted(summary["categories"].items()):
        print(f"{category}: {counts['passed']}/{counts['total']}")
    coverage = summary["reference_coverage"]
    print(f"Exact reference coverage (diagnostic): {coverage['covered']}/{coverage['total']}")
    if args.report is not None:
        report = {
            "schema_version": 1,
            "scoring": {"pass": "Expected sources all returned, no unexpected sources; unsupported questions return no chunks.",
                        "reference_coverage": "Diagnostic exact normalized quote coverage; equivalent wording can be missed. Not answer accuracy."},
            "dataset_sha256": digest(EVAL_FILE),
            "corpus_sha256": {name: hashlib.sha256(text.encode("utf-8")).hexdigest()
                              for name, text in load_documents().items()},
            "index_sha256": {"chunks.json": digest(CHUNKS_FILE), "embeddings.npy": digest(EMBEDDINGS_FILE)},
            "models": {"embedding": model_name, "reranker": RERANKER_MODEL},
            "versions": {"python": platform.python_version(), "sentence-transformers": version("sentence-transformers"),
                         "transformers": version("transformers"), "torch": version("torch")},
            "parameters": {"candidate_count": DEFAULT_CANDIDATE_COUNT, "hybrid_min_score": DEFAULT_HYBRID_MIN_SCORE,
                           "top_n": DEFAULT_TOP_N, "rerank_min_score": DEFAULT_RERANK_MIN_SCORE},
            "summary": summary,
            "cases": evaluations,
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"JSON report: {args.report}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
