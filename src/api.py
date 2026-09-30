from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.langgraph_agent import LangGraphAgentService


class AskRequest(BaseModel):
    question: str


class EvidenceItem(BaseModel):
    chunk_number: int
    source: str
    rerank_score: float
    hybrid_score: float


class AskResponse(BaseModel):
    answer: str
    sources: list[str]
    evidence: list[EvidenceItem]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Start the LangGraph/MCP service once when FastAPI starts.
    Reuse it for every request.
    """

    print("Starting RAG Ops API...")

    agent_service = LangGraphAgentService()

    await agent_service.start()

    app.state.agent_service = agent_service

    print("RAG Ops API ready.")

    try:
        yield

    finally:
        print("Stopping RAG Ops API...")

        await agent_service.close()

        print("RAG Ops API stopped.")


app = FastAPI(
    title="RAG Ops Assistant",
    description=(
        "LangGraph + Amazon Bedrock + MCP + RAG "
        "operations assistant."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "rag-ops-assistant",
    }


@app.post(
    "/ask",
    response_model=AskResponse,
)
async def ask(
    request: AskRequest,
):
    question = request.question.strip()

    if not question:
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty.",
        )

    try:
        result = await app.state.agent_service.ask(
            question
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        print(
            f"Agent error: {exc}"
        )

        raise HTTPException(
            status_code=500,
            detail="The agent failed to process the question.",
        ) from exc

    return AskResponse(
        answer=result["answer"],
        sources=result["sources"],
        evidence=[
            EvidenceItem(
                **item
            )
            for item in result["evidence"]
        ],
    )