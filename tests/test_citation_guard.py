"""Offline regression tests for evidence-chunk citation alignment."""

import pytest

from src.citation_guard import citations_match_evidence


@pytest.mark.parametrize(
    "answer,evidence,expected",
    [
        ("Private DNS [Chunk 9].", [{"chunk_number": 9}], True),
        ("Private DNS [9].", [{"chunk_number": 9}], True),
        ("DNS [9, 10].", [{"chunk_number": 9}, {"chunk_number": 10}], True),
        ("DNS [CHUNKS 9, 10].", [{"chunk_number": 9}, {"chunk_number": 10}], True),
        ("DNS [1] and [3].", [{"chunk_number": 9}, {"chunk_number": 30}], False),
        ("DNS [Chunk 9] and [Chunk 3].", [{"chunk_number": 9}], False),
        ("DNS [9, 99].", [{"chunk_number": 9}], False),
        ("DNS [9].", [], False),
        ("DNS has no inline citation.", [{"chunk_number": 9}], True),
    ],
)
def test_citation_matches_evidence_chunk_ids(answer, evidence, expected):
    assert citations_match_evidence(answer, evidence) is expected
