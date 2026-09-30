import boto3
from sentence_transformers import CrossEncoder, SentenceTransformer

from rag_core import (
    RERANKER_MODEL,
    build_context,
    hybrid_search,
    load_index,
    rerank_results,
)


BEDROCK_REGION = "eu-west-2"
BEDROCK_MODEL_ID = "global.amazon.nova-2-lite-v1:0"


def generate_answer(prompt: str) -> str:
    client = boto3.client(
        "bedrock-runtime",
        region_name=BEDROCK_REGION,
    )

    response = client.converse(
        modelId=BEDROCK_MODEL_ID,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "text": prompt,
                    }
                ],
            }
        ],
        inferenceConfig={
            "temperature": 0.1,
            "maxTokens": 700,
        },
    )

    return response[
        "output"
    ]["message"]["content"][0]["text"]


def main():
    print("Loading saved RAG index...")

    embeddings, metadata = load_index()

    chunk_records = metadata["chunks"]
    model_name = metadata["embedding_model"]

    print(f"Loaded {len(chunk_records)} chunks")
    print(f"Embedding matrix shape: {embeddings.shape}")
    print(f"Embedding model: {model_name}")

    print("\nLoading query embedding model...")
    model = SentenceTransformer(model_name)

    print("Loading reranker model...")
    reranker = CrossEncoder(RERANKER_MODEL)

    while True:
        query = input(
            "\nAsk a question (or type 'exit'): "
        ).strip()

        if query.lower() in {"exit", "quit"}:
            print("Goodbye.")
            break

        if not query:
            print("Please enter a question.")
            continue

        candidates = hybrid_search(
            query=query,
            chunk_records=chunk_records,
            embeddings=embeddings,
            model=model,
        )

        if not candidates:
            print(
                "\n--- NO RELEVANT EVIDENCE ---"
                "\nI couldn't find sufficiently relevant "
                "information in the knowledge base "
                "to answer that question."
            )
            continue

        results = rerank_results(
            query=query,
            candidates=candidates,
            reranker=reranker,
        )

        if not results:
            print(
                "\n--- NO STRONG EVIDENCE AFTER RERANKING ---"
                "\nThe initial search found possible matches, "
                "but none were strong enough after reranking."
            )
            continue

        print(f"\nQuestion: {query}")

        for result in results:
            print(
                f"\n--- CHUNK "
                f"{result['chunk_number']} ---"
            )

            print(
                f"Rerank score:   "
                f"{result['rerank_score']:.4f}"
            )

            print(
                f"Hybrid score:   "
                f"{result['hybrid_score']:.4f}"
            )

            print(
                f"Semantic score: "
                f"{result['semantic_score']:.4f}"
            )

            print(
                f"Keyword score:  "
                f"{result['keyword_score']:.4f}"
            )

            print(f"Source: {result['source']}")
            print(result["text"])

        context = build_context(results)

        prompt = f"""
You are an operations assistant.

Answer the user's question using only the supplied context.

Rules:
- Do not add facts that are not supported by the context.
- If the context does not contain enough information, say so.
- Cite the supporting chunk number after each important claim.
- Use only the most relevant supporting chunks.
- Distinguish authentication, authorization, and network connectivity accurately.

Question:
{query}

Context:
{context}

Answer:
"""

        answer = generate_answer(prompt)

        print("\n--- FINAL ANSWER ---")
        print(answer)


if __name__ == "__main__":
    main()