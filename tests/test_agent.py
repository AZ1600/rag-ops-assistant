import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from src import langgraph_agent as agent


def mcp_result(payload=None, text=None, error=False):
    return SimpleNamespace(
        structured_content=payload,
        content=[] if text is None else [SimpleNamespace(text=text)],
        is_error=error,
    )


def tool_request(name="search_knowledge_base", question="dns"):
    return {"stopReason": "tool_use", "output": {"message": {
        "role": "assistant", "content": [{"toolUse": {
            "toolUseId": "call-1", "name": name, "input": {"question": question},
        }}],
    }}}


def answer(text):
    return {"stopReason": "end_turn", "output": {"message": {
        "role": "assistant", "content": [{"text": text}],
    }}}


@pytest.fixture
def service_factory(monkeypatch):
    services = []

    def create(responses, results):
        class Bedrock:
            def __init__(self):
                self.calls = []
                self.responses = iter(responses)

            def converse(self, **kwargs):
                self.calls.append(deepcopy(kwargs))
                return next(self.responses)

        class MCP:
            def __init__(self):
                self.calls = []
                self.results = iter(results)
                self.entered = self.closed = self.discovered = 0

            async def __aenter__(self):
                self.entered += 1
                return self

            async def __aexit__(self, *args):
                self.closed += 1

            async def list_tools(self):
                self.discovered += 1
                return SimpleNamespace(tools=[SimpleNamespace(
                    name="search_knowledge_base", description="Search docs",
                    input_schema={"type": "object", "properties": {"question": {"type": "string"}}},
                )])

            async def call_tool(self, name, tool_input):
                self.calls.append((name, tool_input))
                result = next(self.results)
                if isinstance(result, Exception):
                    raise result
                return result

        bedrock, mcp = Bedrock(), MCP()
        monkeypatch.setattr(agent.boto3, "client", lambda *args, **kwargs: bedrock)
        monkeypatch.setattr(agent, "Client", lambda params: mcp)
        service = agent.LangGraphAgentService()
        services.append(service)
        return service, bedrock, mcp

    yield create
    assert all(service.exit_stack is None for service in services), "Tests must close MCP sessions"


def test_real_graph_calls_tool_then_returns_answer_with_evidence(service_factory):
    evidence = {"chunk_number": 7, "source": "network.md", "rerank_score": 4.0, "hybrid_score": 0.8}
    service, bedrock, mcp = service_factory(
        [tool_request(), answer("Use a private DNS zone [Chunk 7].")],
        [mcp_result({"found": True, "context": "Private DNS evidence", "sources": ["network.md", "network.md"], "evidence": [evidence]})],
    )

    async def scenario():
        await service.start()
        await service.start()
        try:
            return await service.ask("  dns  ")
        finally:
            await service.close()

    result = asyncio.run(scenario())
    assert result == {"answer": "Use a private DNS zone [Chunk 7].", "sources": ["network.md"], "evidence": [evidence]}
    assert mcp.calls == [("search_knowledge_base", {"question": "dns"})]
    assert (mcp.entered, mcp.closed, mcp.discovered) == (1, 1, 1)
    assert len(bedrock.calls) == 2
    assert bedrock.calls[0]["messages"] == [{"role": "user", "content": [{"text": "dns"}]}]
    tool_result = bedrock.calls[1]["messages"][-1]["content"][0]["toolResult"]
    assert tool_result["toolUseId"] == "call-1"
    assert tool_result["content"][0]["json"]["evidence"] == [evidence]
    assert bedrock.calls[0]["toolConfig"]["tools"][0]["toolSpec"]["name"] == "search_knowledge_base"


def test_no_evidence_stops_graph_without_a_second_model_call(service_factory):
    service, bedrock, mcp = service_factory(
        [tool_request()], [mcp_result({"found": False, "sources": [], "evidence": []})],
    )

    async def scenario():
        await service.start()
        try:
            return await service.ask("annual leave")
        finally:
            await service.close()

    result = asyncio.run(scenario())
    assert result == {
        "answer": "The knowledge base does not contain sufficient information to answer that question.",
        "sources": [], "evidence": [],
    }
    assert len(bedrock.calls) == 1
    assert len(mcp.calls) == 1


def test_separate_questions_do_not_inherit_messages_or_sources(service_factory):
    service, bedrock, _ = service_factory(
        [tool_request(), answer("DNS answer"), answer("Hello")],
        [mcp_result({"found": True, "sources": ["network.md"], "evidence": [{"chunk_number": 1}]})],
    )

    async def scenario():
        await service.start()
        try:
            first = await service.ask("dns")
            second = await service.ask("hello")
            return first, second
        finally:
            await service.close()

    first, second = asyncio.run(scenario())
    assert first["sources"] == ["network.md"]
    assert second == {"answer": "Hello", "sources": [], "evidence": []}
    assert bedrock.calls[2]["messages"] == [{"role": "user", "content": [{"text": "hello"}]}]


@pytest.mark.parametrize("failure", ["structured_error", "text_error", "exception", "unknown_tool"])
def test_tool_failures_do_not_continue_to_model_generation(service_factory, failure):
    responses = [tool_request(name="unknown" if failure == "unknown_tool" else "search_knowledge_base")]
    results = {
        "structured_error": [mcp_result({"found": True, "sources": ["untrusted.md"]}, error=True)],
        "text_error": [mcp_result(text="Tool unavailable", error=True)],
        "exception": [RuntimeError("Connection lost")],
        "unknown_tool": [],
    }[failure]
    service, bedrock, mcp = service_factory(responses, results)

    async def scenario():
        await service.start()
        try:
            with pytest.raises(RuntimeError):
                await service.ask("dns")
        finally:
            await service.close()

    asyncio.run(scenario())
    assert len(bedrock.calls) == 1
    assert len(mcp.calls) == (0 if failure == "unknown_tool" else 1)


@pytest.mark.parametrize("question,expected_error", [(" \n ", ValueError), ("dns", RuntimeError)])
def test_ask_rejects_blank_question_or_unstarted_service(service_factory, question, expected_error):
    service, bedrock, mcp = service_factory([], [])
    with pytest.raises(expected_error):
        asyncio.run(service.ask(question))
    assert bedrock.calls == mcp.calls == []


@pytest.mark.parametrize("result,expected", [
    (mcp_result({"found": False}), {"found": False}),
    (mcp_result(text='{"found": false}'), {"found": False}),
    (mcp_result(text="plain text"), {"result": "plain text"}),
    (mcp_result(text="[1, 2]"), {"result": [1, 2]}),
    (mcp_result(), {"result": None}),
    (mcp_result(text="failed", error=True), {"error": "failed"}),
])
def test_mcp_result_conversion(result, expected):
    assert agent.mcp_result_to_payload(result) == expected


def test_mcp_error_flag_takes_precedence_over_structured_content():
    result = agent.mcp_result_to_payload(mcp_result({"found": True}, text="failed", error=True))
    assert result == {"error": "failed"}
