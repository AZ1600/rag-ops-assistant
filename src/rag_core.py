from pathlib import Path
import json
import re

import numpy as np


INDEX_DIR = Path("index")
EMBEDDINGS_FILE = INDEX_DIR / "embeddings.npy"
CHUNKS_FILE = INDEX_DIR / "chunks.json"

RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
CHUNKING_VERSION = "markdown-sections-v1"
GROUNDING_VERSION = "literal-cloud-ids-duration-v1"
RERANKING_VERSION = "quiet-service-alias-v1"

DEFAULT_CANDIDATE_COUNT = 8
DEFAULT_HYBRID_MIN_SCORE = 0.35
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
            "RAG index not found. Run: python -m src.ingest"
        )

    embeddings = np.load(EMBEDDINGS_FILE)

    with CHUNKS_FILE.open(
        "r",
        encoding="utf-8",
    ) as file:
        metadata = json.load(file)

    if metadata.get("chunking_version") != CHUNKING_VERSION:
        raise SystemExit("RAG index uses an older chunking format. Rebuild: python -m src.ingest")

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
    candidates = factual_value_evidence(query, candidates)
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

    # Retry an explicitly documented terminology alias only after the original
    # question fails. Keep the same candidates, literal-value guards and cutoff.
    alias = rerank_query_alias(query) if not relevant_results else query
    if alias != query:
        alias_scores = reranker.predict([[alias, candidate["text"]] for candidate in candidates])
        relevant_results = [
            dict(candidate, rerank_score=float(score), rerank_query=alias)
            for candidate, score in zip(candidates, alias_scores)
            if float(score) >= min_rerank_score
        ]
        relevant_results.sort(key=lambda item: item["rerank_score"], reverse=True)

    return relevant_results[:top_n]


def rerank_query_alias(query: str) -> str:
    """One curated operations alias; not an LLM rewrite or general synonym map.

    A quiet service/application can describe an idle application. The retry
    still has to pass the original reranker cutoff; it cannot add evidence.
    """
    return re.sub(
        r"\b(?:a\s+)?quiet\s+(services?|applications?|apps?)\b",
        lambda match: ("an " if re.match(r"a\s", match.group(0), re.I) else "")
        + ("idle applications" if match.group(1).lower().endswith("s") else "idle application"),
        query,
        flags=re.I,
    )


def factual_value_evidence(query: str, candidates: list[dict]) -> list[dict]:
    """Require literal values for explicit cloud-ID or quantified-duration requests.

    Topic relevance (for example, an SSO roadmap) cannot establish a configured
    identifier or retention duration. Conceptual questions remain ordinary requests. This is
    a narrow grounding guard, not general answerability or live-value validation.
    """
    if re.search(r"^\s*how\s+many\s+(?:calendar\s+|business\s+)?(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?)\b", query, re.I):
        duration = re.compile(
            r"\b(?:\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
            r"\s*-?\s*(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?)\b", re.I,
        )
        return [candidate for candidate in candidates if duration.search(candidate["text"])]
    if not re.search(r"^\s*(?:what(?:\s+(?:is|are)|['’]s)|which|(?:please\s+)?(?:show|give|tell)\s+me|provide)\b", query, re.I):
        return candidates
    if re.search(r"^\s*what(?:\s+is|['’]s)\s+(?:a|an)\b|\b(?:used for|mean|purpose|format)\b", query, re.I):
        return candidates
    requested = set(re.findall(r"\b(tenant|client|subscription|account)[\s_-]*(?:ids?|identifiers?)\b", query, re.I))
    requested = {kind.lower() for kind in requested}
    if not requested:
        return candidates
    uuid = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
    patterns = {}
    for kind in requested:
        value = rf"(?:{uuid}|\d{{12}})" if kind == "account" else uuid
        patterns[kind] = re.compile(
            rf"\b(?:azure[\s_-]*|aws[\s_-]*)?{kind}[\s_-]*(?:id|identifier)"
            rf"[\"'`]*\s*(?:[:=|]|\bis\b)\s*[\"'`<]*({value})(?![\w-])", re.I,
        )
    matches = []
    supported = set()
    for candidate in candidates:
        kinds = set()
        for kind, pattern in patterns.items():
            if any(set(match.group(1).replace("-", "")) != {"0"}
                   for match in pattern.finditer(candidate["text"])):
                kinds.add(kind)
        if kinds:
            matches.append(candidate)
            supported.update(kinds)
    return matches if requested.issubset(supported) else []


def build_context(results: list[dict]) -> str:
    context_parts = []

    for result in results:
        context_parts.append(
            f"[Chunk {result['chunk_number']}]\n"
            f"Source: {result['source']}\n"
            f"{result['text']}"
        )

    return "\n\n".join(context_parts)
