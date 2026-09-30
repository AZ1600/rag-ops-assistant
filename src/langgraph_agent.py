import asyncio
import json
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import TypedDict

import boto3
from langgraph.graph import END, START, StateGraph
from mcp import Client, StdioServerParameters


BEDROCK_REGION = "eu-west-2"
BEDROCK_MODEL_ID = "global.amazon.nova-2-lite-v1:0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent


SYSTEM_PROMPT = """
You are an operations assistant.

You have access to tools exposed through an MCP server.

Rules:
- Use the knowledge-base search tool when the user asks about
  CloudOps, PlatformPilot, Azure infrastructure, Kubernetes,
  observability, or documented project information.
- For documentation questions, answer only from evidence returned
  by the knowledge-base tool.
- Do not invent implementation details.
- Cite important claims using chunk numbers when available.
- If the knowledge-base tool reports that no relevant evidence
  was found, do not invent an answer.
"""


class AgentState(TypedDict):
    messages: list[dict]
    stop_reason: str
    final_answer: str
    sources: list[str]
    evidence: list[dict]


def convert_mcp_tools_to_bedrock(mcp_tools):
    """
    Convert MCP-discovered tools into the format
    expected by Amazon Bedrock Converse.
    """

    bedrock_tools = []

    for tool in mcp_tools:
        bedrock_tools.append(
            {
                "toolSpec": {
                    "name": tool.name,
                    "description": (
                        tool.description
                        or f"MCP tool: {tool.name}"
                    ),
                    "inputSchema": {
                        "json": tool.input_schema,
                    },
                }
            }
        )

    return bedrock_tools


def mcp_result_to_payload(result) -> dict:
    """
    Convert an MCP tool result into a normal Python dictionary.
    """

    if result.structured_content is not None:
        return result.structured_content

    text_parts = []

    for block in result.content:
        text = getattr(block, "text", None)

        if text:
            text_parts.append(text)

    combined_text = "\n".join(text_parts)

    if result.is_error:
        return {
            "error": (
                combined_text
                or "The MCP tool returned an error."
            )
        }

    if not combined_text:
        return {
            "result": None,
        }

    try:
        parsed = json.loads(combined_text)

        if isinstance(parsed, dict):
            return parsed

        return {
            "result": parsed,
        }

    except json.JSONDecodeError:
        return {
            "result": combined_text,
        }


class LangGraphAgentService:
    """
    Long-lived LangGraph agent service.

    MCP, tool discovery, and graph compilation happen once.
    Multiple questions can then reuse the same service.
    """

    def __init__(self):
        self.bedrock_client = boto3.client(
            "bedrock-runtime",
            region_name=BEDROCK_REGION,
        )

        self.server_params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "src.mcp_server",
            ],
            cwd=str(PROJECT_ROOT),
        )

        self.exit_stack = None
        self.mcp_client = None
        self.bedrock_tools = []
        self.known_tool_names = set()
        self.graph = None

    async def start(self):
        """
        Start MCP, discover tools, and compile LangGraph.
        """

        if self.graph is not None:
            return

        print("Starting LangGraph agent service...")

        self.exit_stack = AsyncExitStack()

        self.mcp_client = await self.exit_stack.enter_async_context(
            Client(self.server_params)
        )

        print("Connected to MCP server.")

        tool_response = await self.mcp_client.list_tools()

        mcp_tools = tool_response.tools

        print(
            "MCP tools discovered:",
            [
                tool.name
                for tool in mcp_tools
            ],
        )

        self.bedrock_tools = convert_mcp_tools_to_bedrock(
            mcp_tools
        )

        self.known_tool_names = {
            tool.name
            for tool in mcp_tools
        }

        self.graph = self._build_graph()

        print("LangGraph agent service ready.")

    async def close(self):
        """
        Shut down the persistent MCP connection.
        """

        if self.exit_stack is not None:
            await self.exit_stack.aclose()

        self.exit_stack = None
        self.mcp_client = None
        self.graph = None

        print("LangGraph agent service stopped.")

    async def _bedrock_node(
        self,
        state: AgentState,
    ) -> AgentState:
        """
        Ask Bedrock what to do next.
        """

        print("\n--- BEDROCK NODE ---")

        response = self.bedrock_client.converse(
            modelId=BEDROCK_MODEL_ID,
            system=[
                {
                    "text": SYSTEM_PROMPT,
                }
            ],
            messages=state["messages"],
            toolConfig={
                "tools": self.bedrock_tools,
            },
            inferenceConfig={
                "temperature": 0.1,
                "maxTokens": 700,
            },
        )

        stop_reason = response["stopReason"]

        assistant_message = response[
            "output"
        ]["message"]

        messages = (
            state["messages"]
            + [assistant_message]
        )

        print(
            f"Stop reason: {stop_reason}"
        )

        final_answer = ""

        if stop_reason != "tool_use":
            text_parts = []

            for block in assistant_message[
                "content"
            ]:
                if "text" in block:
                    text_parts.append(
                        block["text"]
                    )

            final_answer = "\n".join(
                text_parts
            )

        return {
            "messages": messages,
            "stop_reason": stop_reason,
            "final_answer": final_answer,
            "sources": state["sources"],
            "evidence": state["evidence"],
        }

    async def _mcp_tool_node(
        self,
        state: AgentState,
    ) -> AgentState:
        """
        Execute MCP tool requests made by Bedrock.
        """

        print("\n--- MCP TOOL NODE ---")

        assistant_message = state[
            "messages"
        ][-1]

        tool_results = []

        no_evidence = False

        sources = list(
            state["sources"]
        )

        evidence = list(
            state["evidence"]
        )

        for block in assistant_message[
            "content"
        ]:
            if "toolUse" not in block:
                continue

            tool_use = block["toolUse"]

            tool_name = tool_use["name"]

            tool_use_id = tool_use[
                "toolUseId"
            ]

            tool_input = tool_use["input"]

            print(
                f"Tool requested: {tool_name}"
            )

            print(
                f"Tool input: {tool_input}"
            )

            if tool_name not in self.known_tool_names:
                payload = {
                    "error": (
                        f"Unknown MCP tool: "
                        f"{tool_name}"
                    )
                }

            else:
                result = await self.mcp_client.call_tool(
                    tool_name,
                    tool_input,
                )

                payload = mcp_result_to_payload(
                    result
                )

            print("MCP tool completed.")

            if "found" in payload:
                print(
                    f"Evidence found: "
                    f"{payload['found']}"
                )

            if "sources" in payload:
                print(
                    f"Sources: "
                    f"{payload['sources']}"
                )

            if payload.get("found") is False:
                no_evidence = True

            # ---------------------------------------------
            # Save source metadata in LangGraph state
            # ---------------------------------------------

            for source in payload.get(
                "sources",
                [],
            ):
                if source not in sources:
                    sources.append(
                        source
                    )

            # ---------------------------------------------
            # Save evidence metadata in LangGraph state
            # ---------------------------------------------

            payload_evidence = payload.get(
                "evidence",
                [],
            )

            if isinstance(
                payload_evidence,
                list,
            ):
                for item in payload_evidence:
                    if isinstance(item, dict):
                        evidence.append(
                            item
                        )

            # ---------------------------------------------
            # Send tool result back to Bedrock
            # ---------------------------------------------

            tool_results.append(
                {
                    "toolResult": {
                        "toolUseId": tool_use_id,
                        "content": [
                            {
                                "json": payload,
                            }
                        ],
                    }
                }
            )

        if not tool_results:
            raise RuntimeError(
                "Bedrock requested tool use "
                "but provided no tool call."
            )

        messages = (
            state["messages"]
            + [
                {
                    "role": "user",
                    "content": tool_results,
                }
            ]
        )

        # Hard no-evidence guard.
        if no_evidence:
            return {
                "messages": messages,
                "stop_reason": "no_evidence",
                "final_answer": (
                    "The knowledge base does not contain "
                    "sufficient information to answer "
                    "that question."
                ),
                "sources": sources,
                "evidence": evidence,
            }

        return {
            "messages": messages,
            "stop_reason": "",
            "final_answer": "",
            "sources": sources,
            "evidence": evidence,
        }

    @staticmethod
    def _route_after_bedrock(
        state: AgentState,
    ) -> str:
        if state["stop_reason"] == "tool_use":
            return "tool"

        return "end"

    @staticmethod
    def _route_after_tool(
        state: AgentState,
    ) -> str:
        if state["stop_reason"] == "no_evidence":
            return "end"

        return "bedrock"

    def _build_graph(self):
        """
        Build and compile the LangGraph workflow.
        """

        builder = StateGraph(
            AgentState
        )

        builder.add_node(
            "bedrock",
            self._bedrock_node,
        )

        builder.add_node(
            "tool",
            self._mcp_tool_node,
        )

        builder.add_edge(
            START,
            "bedrock",
        )

        builder.add_conditional_edges(
            "bedrock",
            self._route_after_bedrock,
            {
                "tool": "tool",
                "end": END,
            },
        )

        builder.add_conditional_edges(
            "tool",
            self._route_after_tool,
            {
                "bedrock": "bedrock",
                "end": END,
            },
        )

        return builder.compile()

    async def ask(
        self,
        question: str,
    ) -> dict:
        """
        Run one question through the persistent graph.
        """

        question = question.strip()

        if not question:
            raise ValueError(
                "Question cannot be empty."
            )

        if self.graph is None:
            raise RuntimeError(
                "Agent service has not been started."
            )

        initial_state: AgentState = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "text": question,
                        }
                    ],
                }
            ],
            "stop_reason": "",
            "final_answer": "",
            "sources": [],
            "evidence": [],
        }

        final_state = await self.graph.ainvoke(
            initial_state
        )

        return {
            "answer": final_state["final_answer"],
            "sources": final_state["sources"],
            "evidence": final_state["evidence"],
        }


async def run_agent(
    question: str,
) -> dict:
    """
    Convenience wrapper for terminal testing.
    """

    service = LangGraphAgentService()

    await service.start()

    try:
        return await service.ask(
            question
        )

    finally:
        await service.close()


def main():
    question = input(
        "\nAsk the LangGraph agent a question: "
    ).strip()

    if not question:
        raise SystemExit(
            "No question entered."
        )

    result = asyncio.run(
        run_agent(question)
    )

    print(
        "\n--- FINAL ANSWER ---"
    )

    print(
        result["answer"]
    )

    print(
        "\n--- SOURCES ---"
    )

    print(
        result["sources"]
    )

    print(
        "\n--- EVIDENCE ---"
    )

    print(
        result["evidence"]
    )


if __name__ == "__main__":
    main()