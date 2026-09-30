from pathlib import Path
import json

import numpy as np
from sentence_transformers import SentenceTransformer


DATA_DIR = Path("data")
INDEX_DIR = Path("index")

MODEL_NAME = "all-MiniLM-L6-v2"


def load_document(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def chunk_text(text: str, max_chars: int = 800) -> list[str]:
    paragraphs = [
        paragraph.strip()
        for paragraph in text.split("\n\n")
        if paragraph.strip()
    ]

    chunks = []
    current_chunk = ""

    for paragraph in paragraphs:
        candidate = (
            f"{current_chunk}\n\n{paragraph}"
            if current_chunk
            else paragraph
        )

        if len(candidate) <= max_chars:
            current_chunk = candidate
        else:
            if current_chunk:
                chunks.append(current_chunk)

            current_chunk = paragraph

    if current_chunk:
        chunks.append(current_chunk)

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