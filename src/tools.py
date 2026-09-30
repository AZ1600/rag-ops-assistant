import sys

from sentence_transformers import CrossEncoder, SentenceTransformer

from src.rag_core import (
    RERANKER_MODEL,
    build_context,
    hybrid_search,
    load_index,
    rerank_results,
)


SEARCH_KNOWLEDGE_BASE_TOOL_SPEC = {
    "toolSpec": {
        "name": "search_knowledge_base",
        "description": (
            "Search the operations knowledge base for information "
            "about infrastructure, CloudOps, PlatformPilot, Azure, "
            "Kubernetes, and observability."
        ),
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": (
                            "The question to search for in the "
                            "knowledge base."
                        ),
                    }
                },
                "required": ["question"],
            }
        },
    }
}


class KnowledgeBaseTool:
    def __init__(self):
        print(
            "Loading knowledge-base tool...",
            file=sys.stderr,
        )

        self.embeddings, metadata = load_index()

        self.chunk_records = metadata["chunks"]
        self.model_name = metadata["embedding_model"]

        self.embedding_model = SentenceTransformer(
            self.model_name
        )

        self.reranker = CrossEncoder(
            RERANKER_MODEL
        )

        print(
            "Knowledge-base tool ready.",
            file=sys.stderr,
        )

    def search(
        self,
        question: str,
    ) -> dict:
        question = question.strip()

        if not question:
            return {
                "found": False,
                "message": "Question cannot be empty.",
                "context": "",
                "sources": [],
                "evidence": [],
            }

        candidates = hybrid_search(
            query=question,
            chunk_records=self.chunk_records,
            embeddings=self.embeddings,
            model=self.embedding_model,
        )

        if not candidates:
            return {
                "found": False,
                "message": (
                    "No sufficiently relevant evidence "
                    "was found in the knowledge base."
                ),
                "context": "",
                "sources": [],
                "evidence": [],
            }

        results = rerank_results(
            query=question,
            candidates=candidates,
            reranker=self.reranker,
        )

        if not results:
            return {
                "found": False,
                "message": (
                    "Possible matches were found, but "
                    "none were strong enough after reranking."
                ),
                "context": "",
                "sources": [],
                "evidence": [],
            }

        context = build_context(results)

        sources = list(
            dict.fromkeys(
                result["source"]
                for result in results
            )
        )

        evidence = [
            {
                "chunk_number": result["chunk_number"],
                "source": result["source"],
                "rerank_score": result["rerank_score"],
                "hybrid_score": result["hybrid_score"],
            }
            for result in results
        ]

        return {
            "found": True,
            "message": "Relevant evidence found.",
            "context": context,
            "sources": sources,
            "evidence": evidence,
        }


def main():
    tool = KnowledgeBaseTool()

    result = tool.search(
        "How does CloudOps prevent unsafe remediation?"
    )

    print("\n--- TOOL RESULT ---")
    print(f"Found: {result['found']}")
    print(f"Sources: {result['sources']}")
    print(f"Evidence: {result['evidence']}")
    print("\nContext:")
    print(result["context"])


if __name__ == "__main__":
    main()