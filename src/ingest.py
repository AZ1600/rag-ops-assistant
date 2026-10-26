from pathlib import Path
import json
import re

import numpy as np
from sentence_transformers import SentenceTransformer

from src.rag_core import CHUNKING_VERSION


DATA_DIR = Path("data")
INDEX_DIR = Path("index")

MODEL_NAME = "all-MiniLM-L6-v2"


def load_document(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def chunk_text(text: str, max_chars: int = 800) -> list[str]:
    """Keep Markdown sections separate and repeat their headings on long sections.

    The size is a soft limit: an indivisible paragraph can exceed it,
    as before. Heading-like lines inside fenced code are treated as content.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive.")
    sections = []
    body = []
    headings = []
    document_heading = None
    fence = None
    for line in text.splitlines():
        fence_match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence_match:
            marker, tail = fence_match.groups()
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence) and not tail.strip():
                fence = None
            body.append(line)
            continue
        heading = re.match(r"^ {0,3}(#{1,6})\s+\S", line) if fence is None else None
        if heading:
            sections.append((list(headings), body))
            body = []
            level = len(heading.group(1))
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, line.strip()))
            if document_heading is None:
                document_heading = line.strip()
        else:
            body.append(line)
    sections.append((list(headings), body))

    chunks = []
    for section_headings, lines in sections:
        if not any(line.strip() and line.strip() not in {"---", "***", "___"} for line in lines):
            continue
        labels = [label for _, label in section_headings]
        if document_heading and labels and document_heading not in labels:
            labels.insert(0, document_heading)
        prefix = "\n".join(labels)
        paragraphs = [p.strip() for p in "\n".join(lines).split("\n\n") if p.strip()]
        current = ""
        for paragraph in paragraphs:
            candidate = f"{current}\n\n{paragraph}" if current else paragraph
            rendered = f"{prefix}\n\n{candidate}" if prefix else candidate
            if current and len(rendered) > max_chars:
                chunks.append(f"{prefix}\n\n{current}" if prefix else current)
                current = paragraph
            else:
                current = candidate
        if current:
            chunks.append(f"{prefix}\n\n{current}" if prefix else current)
    return chunks


def load_all_documents() -> list[dict]:
    document_files = sorted(DATA_DIR.glob("*.md"))

    if not document_files:
        raise SystemExit("No Markdown documents found in data/")

    chunk_records = []

    for document_file in document_files:
        print(f"Reading: {document_file.name}")

        document = load_document(document_file)
        chunks = chunk_text(document)

        print(f"  Characters: {len(document)}")
        print(f"  Chunks:     {len(chunks)}")

        for chunk in chunks:
            chunk_records.append(
                {
                    "source": document_file.name,
                    "text": chunk,
                }
            )

    return chunk_records


def main():
    print("Loading documents...\n")

    chunk_records = load_all_documents()

    for chunk_number, record in enumerate(
        chunk_records,
        start=1,
    ):
        record["chunk_number"] = chunk_number

    texts = [
        record["text"]
        for record in chunk_records
    ]

    print(f"\nTotal chunks: {len(chunk_records)}")

    print("\nLoading embedding model...")

    model = SentenceTransformer(MODEL_NAME)

    print("Creating embeddings...")

    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
    )

    INDEX_DIR.mkdir(exist_ok=True)

    embeddings_file = INDEX_DIR / "embeddings.npy"
    chunks_file = INDEX_DIR / "chunks.json"

    np.save(
        embeddings_file,
        embeddings,
    )

    with chunks_file.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            {
                "embedding_model": MODEL_NAME,
                "chunking_version": CHUNKING_VERSION,
                "chunks": chunk_records,
            },
            file,
            indent=2,
        )

    print("\nIndex created successfully.")
    print(f"Documents:  {len(list(DATA_DIR.glob('*.md')))}")
    print(f"Chunks:     {len(chunk_records)}")
    print(f"Embeddings: {embeddings_file}")
    print(f"Metadata:   {chunks_file}")
    print(f"Shape:      {embeddings.shape}")


if __name__ == "__main__":
    main()
