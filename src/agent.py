import boto3

from src.tools import (
    KnowledgeBaseTool,
    SEARCH_KNOWLEDGE_BASE_TOOL_SPEC,
)


BEDROCK_REGION = "eu-west-2"
BEDROCK_MODEL_ID = "global.amazon.nova-2-lite-v1:0"

MAX_AGENT_STEPS = 5


SYSTEM_PROMPT = """
You are an operations assistant.

You have access to tools.

Rules:
- Use the knowledge-base tool when the user asks about systems,
  projects, infrastructure, CloudOps, PlatformPilot, Azure,
  Kubernetes, or observability covered by the documentation.
- After receiving a tool result, answer only from evidence
  contained in that tool result.
- Do not invent implementation details.
- Do not infer features that are not explicitly supported.
- Cite important knowledge-base claims using chunk numbers,
  for example: [Chunk 34].
- If the knowledge-base tool reports that no relevant evidence
  was found, state only that the knowledge base does not contain
  sufficient information to answer the question.
"""


def execute_tool(
    tool_name: str,
    tool_input: dict,
    knowledge_base: KnowledgeBaseTool,
) -> dict:
    if tool_name == "search_knowledge_base":
        return knowledge_base.search(
            tool_input["question"]
        )

    return {
        "found": False,
        "message": f"Unknown tool: {tool_name}",
        "context": "",
        "sources": [],
        "evidence": [],
    }


def run_agent(question: str):
    client = boto3.client(
        "bedrock-runtime",
        region_name=BEDROCK_REGION,
    )

    knowledge_base = KnowledgeBaseTool()

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

    tools = [
        SEARCH_KNOWLEDGE_BASE_TOOL_SPEC
    ]

    for step in range(1, MAX_AGENT_STEPS + 1):
        print(
            f"\n--- AGENT STEP {step} ---"
        )

        response = client.converse(
            modelId=BEDROCK_MODEL_ID,
            system=[
                {
                    "text": SYSTEM_PROMPT,
                }
            ],
            messages=messages,
            toolConfig={
                "tools": tools
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

            for content_block in assistant_message[
                "content"
            ]:
                if "text" in content_block:
                    print(
                        content_block["text"]
                    )

            return

        tool_results = []

        for content_block in assistant_message[
            "content"
        ]:
            if "toolUse" not in content_block:
                continue

            tool_use = content_block[
                "toolUse"
            ]

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

            result = execute_tool(
                tool_name=tool_name,
                tool_input=tool_input,
                knowledge_base=knowledge_base,
            )

            print(
                f"Tool completed: {tool_name}"
            )

            if "found" in result:
                print(
                    f"Evidence found: "
                    f"{result['found']}"
                )

            if "sources" in result:
                print(
                    f"Sources: "
                    f"{result['sources']}"
                )

            tool_results.append(
                {
                    "toolResult": {
                        "toolUseId": tool_use_id,
                        "content": [
                            {
                                "json": result
                            }
                        ],
                    }
                }
            )

        if not tool_results:
            raise RuntimeError(
                "Bedrock requested tool use "
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
        "Maximum number of agent steps reached."
    )


def main():
    question = input(
        "\nAsk the agent a question: "
    ).strip()

    if not question:
        raise SystemExit(
            "No question entered."
        )

    run_agent(question)


if __name__ == "__main__":
    main()