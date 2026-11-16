"""Check that explicit inline numeric citations reference returned MCP chunks.

This checks label alignment only. It does not validate whether the content of a
chunk supports an answer, nor does it require every answer to contain citations.
"""

import re

INLINE_CITATION_PATTERN = re.compile(
    r"\[(?:chunks?\s+)?(\d+(?:\s*,\s*\d+)*)\]",
    re.IGNORECASE,
)

CITATION_MISMATCH_RESPONSE = (
    "The generated answer contains citation labels that do not match "
    "the retrieved evidence. Please retry or inspect the returned sources."
)


def citations_match_evidence(answer: str, evidence: list[dict]) -> bool:
    """Accept only numeric inline citation labels found in retrieved evidence."""
    cited_chunks = {
        int(part.strip())
        for match in INLINE_CITATION_PATTERN.finditer(answer)
        for part in match.group(1).split(",")
    }
    if not cited_chunks:
        return True

    available_chunks = {
        item["chunk_number"]
        for item in evidence
        if isinstance(item, dict) and type(item.get("chunk_number")) is int
    }
    return cited_chunks.issubset(available_chunks)
