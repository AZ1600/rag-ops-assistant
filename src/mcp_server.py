from mcp.server import MCPServer

from src.tools import KnowledgeBaseTool


mcp = MCPServer(
    "RAG Ops Assistant",
    dependencies=[
        "sentence-transformers",
        "numpy",
    ],
)

knowledge_base = KnowledgeBaseTool()


@mcp.tool()
def search_knowledge_base(question: str) -> dict:
    """
    Search the operations knowledge base for information
    about CloudOps, PlatformPilot, Azure infrastructure,
    Kubernetes, and observability.
    """

    return knowledge_base.search(question)


if __name__ == "__main__":
    mcp.run()