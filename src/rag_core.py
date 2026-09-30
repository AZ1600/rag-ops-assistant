from pathlib import Path
import json
import re

import numpy as np


INDEX_DIR = Path("index")
EMBEDDINGS_FILE = INDEX_DIR / "embeddings.npy"
CHUNKS_FILE = INDEX_DIR / "chunks.json"

RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

DEFAULT_CANDIDATE_COUNT = 8
DEFAULT_HYBRID_MIN_SCORE = 0.40
DEFAULT_TOP_N = 3
DEFAULT_RERANK_MIN_SCORE = -1.0


STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "does",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
}


def load_index():
    if not EMBEDDINGS_FILE.exists() or not CHUNKS_FILE.exists():
        raise SystemExit(
            "RAG index not found. Run: python src/ingest.py"
        )

    embeddings = np.load(EMBEDDINGS_FILE)

    with CHUNKS_FILE.open(
        "r",
        encoding="utf-8",
    ) as file:
        metadata = json.load(file)

    return embeddings, metadata


def tokenize(text: str) -> set[str]:
    words = set(
        re.findall(
            r"[a-zA-Z0-9_-]+",
            text.lower(),
        )
    )

    return words - STOP_WORDS


def keyword_score(
    query: str,
    text: str,
) -> float:
    query_terms = tokenize(query)
    text_terms = tokenize(text)

    if not query_terms:
        return 0.0

    matching_terms = query_terms & text_terms

    return len(matching_terms) / len(query_terms)


def hybrid_search(
    query: str,
    chunk_records: list[dict],
    embeddings,
    model,
    candidate_count: int = DEFAULT_CANDIDATE_COUNT,
    min_score: float = DEFAULT_HYBRID_MIN_SCORE,
):
    query_embedding = model.encode(
        query,
        normalize_embeddings=True,
    )

    semantic_scores = embeddings @ query_embedding

    candidates = []

    for index, chunk in enumerate(chunk_records):
        semantic_score = float(
            semantic_scores[index]
        )

        lexical_score = keyword_score(
            query,
            chunk["text"],
        )

        hybrid_score = (
            semantic_score * 0.75
            + lexical_score * 0.25
        )

        candidates.append(
            {
                "index": index,
                "semantic_score": semantic_score,
                "keyword_score": lexical_score,
                "hybrid_score": hybrid_score,
            }
        )

    candidates.sort(
        key=lambda item: item["hybrid_score"],
        reverse=True,
    )

    results = []

    for candidate in candidates[:candidate_count]:
        if candidate["hybrid_score"] < min_score:
            continue

        index = candidate["index"]
        chunk = chunk_records[index]

        results.append(
            {
                "chunk_number": chunk["chunk_number"],
                "source": chunk["source"],
                "semantic_score": candidate[
                    "semantic_score"
                ],
                "keyword_score": candidate[
                    "keyword_score"
                ],
                "hybrid_score": candidate[
                    "hybrid_score"
                ],
                "text": chunk["text"],
            }
        )

    return results


def rerank_results(
    query: str,
    candidates: list[dict],
    reranker,
    top_n: int = DEFAULT_TOP_N,
    min_rerank_score: float = DEFAULT_RERANK_MIN_SCORE,
):
    if not candidates:
        return []

    pairs = [
        [query, candidate["text"]]
        for candidate in candidates
    ]

    rerank_scores = reranker.predict(pairs)

    for candidate, score in zip(
        candidates,
        rerank_scores,
    ):
        candidate["rerank_score"] = float(score)

    candidates.sort(
        key=lambda item: item["rerank_score"],
        reverse=True,
    )

    relevant_results = [
        candidate
        for candidate in candidates
        if candidate["rerank_score"] >= min_rerank_score
    ]

    return relevant_results[:top_n]


def build_context(results: list[dict]) -> str:
    context_parts = []

    for result in results:
        context_parts.append(
            f"[Chunk {result['chunk_number']}]\n"
            f"Source: {result['source']}\n"
            f"{result['text']}"
        )

    return "\n\n".join(context_parts)