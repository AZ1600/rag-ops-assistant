from pathlib import Path
import json

from sentence_transformers import CrossEncoder, SentenceTransformer

from rag_core import (
    RERANKER_MODEL,
    hybrid_search,
    load_index,
    rerank_results,
)


EVAL_FILE = Path("evals/retrieval_cases.json")


def load_eval_cases():
    with EVAL_FILE.open(
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


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
        }

    if not results:
        return {
            "passed": False,
            "top1_correct": False,
            "source_purity": False,
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

    passed = (
        top1_correct
        and source_purity
    )

    return {
        "passed": passed,
        "top1_correct": top1_correct,
        "source_purity": source_purity,
    }


def main():
    print("Loading RAG index...")

    embeddings, metadata = load_index()

    chunk_records = metadata["chunks"]
    model_name = metadata["embedding_model"]

    print("Loading embedding model...")
    model = SentenceTransformer(model_name)

    print("Loading reranker...")
    reranker = CrossEncoder(RERANKER_MODEL)

    cases = load_eval_cases()

    passed = 0

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

    total = len(cases)

    print("\n--- SUMMARY ---")
    print(f"Passed: {passed}/{total}")
    print(
        f"Accuracy: "
        f"{passed / total:.1%}"
    )


if __name__ == "__main__":
    main()