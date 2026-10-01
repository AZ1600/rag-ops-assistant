FROM python:3.11-slim-trixie

RUN apt-get update \
    && apt-get install --only-upgrade -y \
        openssl \
        libssl3t64 \
        libpcre2-8-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .

# Install CPU-only PyTorch first.
# sentence-transformers will then reuse this instead of pulling
# the much larger CUDA/NVIDIA PyTorch dependency stack.
RUN python -m pip install --upgrade pip \
    && python -m pip install \
        --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch==2.10.0+cpu" \
    && python -m pip install \
        --no-cache-dir \
        -r requirements.txt

COPY . .

# Build the RAG index and cache the embedding model
RUN python -m src.ingest

# Cache the reranker model
RUN python -c \
    'from sentence_transformers import CrossEncoder; CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")'

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]