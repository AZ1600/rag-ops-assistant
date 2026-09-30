import asyncio
import json
import sys
from pathlib import Path

import boto3
from mcp import Client, StdioServerParameters


BEDROCK_REGION = "eu-west-2"
BEDROCK_MODEL_ID = "global.amazon.nova-2-lite-v1:0"

MAX_AGENT_STEPS = 5

PROJECT_ROOT = Path(__file__).resolve().parent.parent


SYSTEM_PROMPT = """
You are an operations assistant.

You have access to tools exposed through an MCP server.

Rules:
- Use the knowledge-base search tool when the user asks about
  CloudOps, PlatformPilot, Azure infrastructure, Kubernetes,
  observability, or documented project information.
- Answer only from evidence returned by the knowledge-base tool
  when answering documentation questions.
- Do not invent implementation details.
- Cite important claims with chunk numbers when available.
- If the knowledge-base tool reports that no relevant evidence
  was found, state only that the knowledge base does not contain
  sufficient information to answer the question.
"""


def convert_mcp_tools_to_bedrock(mcp_tools):
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


async def run_agent(question: str):
    bedrock_client = boto3.client(
        "bedrock-runtime",
        region_name=BEDROCK_REGION,
    )

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "src.mcp_server",
        ],
        cwd=str(PROJECT_ROOT),
    )

    print("\nConnecting to MCP server...")

    async with Client(server_params) as mcp_client:
        print("Connected to MCP server.")

        tool_response = await mcp_client.list_tools()

        mcp_tools = tool_response.tools

        print(
            "MCP tools discovered:",
            [
                tool.name
                for tool in mcp_tools
            ],
        )

        bedrock_tools = convert_mcp_tools_to_bedrock(
            mcp_tools
        )

        known_tool_names = {
            tool.name
            for tool in mcp_tools
        }

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "text": question,
                    }
                ],
            }
        ]

        for step in range(
            1,
            MAX_AGENT_STEPS + 1,
        ):
            print(
                f"\n--- AGENT STEP {step} ---"
            )

            response = bedrock_client.converse(
                modelId=BEDROCK_MODEL_ID,
                system=[
                    {
                        "text": SYSTEM_PROMPT,
                    }
                ],
                messages=messages,
                toolConfig={
                    "tools": bedrock_tools,
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

            messages.append(
                assistant_message
            )

            print(
                f"Stop reason: {stop_reason}"
            )

            if stop_reason != "tool_use":
                print(
                    "\n--- FINAL ANSWER ---"
                )

                for block in assistant_message[
                    "content"
                ]:
                    if "text" in block:
                        print(
                            block["text"]
                        )

                return

            tool_results = []

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
                    f"MCP tool requested: "
                    f"{tool_name}"
                )

                print(
                    f"Tool input: "
                    f"{tool_input}"
                )

                if tool_name not in known_tool_names:
                    payload = {
                        "error": (
                            f"Unknown MCP tool: "
                            f"{tool_name}"
                        )
                    }

                else:
                    mcp_result = (
                        await mcp_client.call_tool(
                            tool_name,
                            tool_input,
                        )
                    )

                    payload = (
                        mcp_result_to_payload(
                            mcp_result
                        )
                    )

                print(
                    "MCP tool completed."
                )

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
                    "Bedrock requested a tool "
                    "but supplied no tool call."
                )

            messages.append(
                {
                    "role": "user",
                    "content": tool_results,
                }
            )

        print(
            "\n--- AGENT STOPPED ---"
        )
        print(
            "Maximum agent steps reached."
        )


def main():
    question = input(
        "\nAsk the MCP agent a question: "
    ).strip()

    if not question:
        raise SystemExit(
            "No question entered."
        )

    asyncio.run(
        run_agent(question)
    )


if __name__ == "__main__":
    main()