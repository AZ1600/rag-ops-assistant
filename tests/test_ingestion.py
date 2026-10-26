import pytest

from src.ingest import chunk_text


def test_unrelated_markdown_sections_are_not_merged():
    text = "# Operations\n\n## Alerts\n\nAn alert fired.\n\n## Idle traffic\n\nNo traffic is not a failure."
    chunks = chunk_text(text)
    assert len(chunks) == 2
    assert all(chunk.startswith("# Operations\n") for chunk in chunks)
    assert "An alert fired." in chunks[0]
    assert "No traffic is not a failure." not in chunks[0]
    assert "## Idle traffic" in chunks[1]
    assert "No traffic is not a failure." in chunks[1]


def test_large_section_repeats_parent_and_section_headings():
    chunks = chunk_text("# Guide\n\n## Network\n\n" + "a" * 30 + "\n\n" + "b" * 30, max_chars=60)
    assert len(chunks) == 2
    assert all(chunk.startswith("# Guide\n## Network\n\n") for chunk in chunks)
    assert "a" * 30 in chunks[0] and "b" * 30 in chunks[1]


@pytest.mark.parametrize("marker", ["```", "~~~~"])
def test_heading_like_code_comments_do_not_split_markdown_sections(marker):
    text = f"# Guide\n\n## Script\n\n{marker}bash\n# comment, not a section\necho ok\n{marker}\n\n## Next\n\nNext instructions."
    chunks = chunk_text(text)
    assert len(chunks) == 2
    assert "# comment, not a section" in chunks[0]
    assert "## Next" not in chunks[0]
    assert "Next instructions." in chunks[1]


def test_fence_only_closes_with_the_same_marker_and_sufficient_length():
    chunks = chunk_text("# Guide\n\n~~~~text\n```\n# inside fence\n~~~\n# still inside\n~~~~\n\n## Outside\n\nDone.")
    assert len(chunks) == 2
    assert "# inside fence" in chunks[0] and "# still inside" in chunks[0]


def test_heading_only_sections_do_not_create_empty_evidence():
    assert chunk_text("# Guide\n\n## Empty\n\n---\n\n## Useful\n\nA fact.") == [
        "# Guide\n## Useful\n\nA fact."
    ]


def test_plain_text_and_empty_documents_still_work():
    assert chunk_text("") == []
    assert chunk_text("First paragraph.\n\nSecond paragraph.") == ["First paragraph.\n\nSecond paragraph."]


def test_long_paragraph_is_preserved_instead_of_dropped():
    paragraph = "x" * 100
    assert chunk_text(paragraph, max_chars=20) == [paragraph]


def test_invalid_chunk_size_is_rejected():
    with pytest.raises(ValueError, match="positive"):
        chunk_text("text", max_chars=0)
