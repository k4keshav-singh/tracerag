# TraceRAG container image.
#
# The embedding model is baked into the image at build time. That makes the
# container start fast and run offline, at the cost of a larger image (the CPU
# torch wheel dominates). Set BAKE_MODEL=false to skip it and download at first
# run instead; the app degrades to keyword-only if the download then fails.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/opt/hf-cache

WORKDIR /app

# curl is needed by the container healthcheck below.
RUN apt-get update \
 && apt-get install --no-install-recommends -y curl \
 && rm -rf /var/lib/apt/lists/*

# Install the CPU torch build explicitly. Without this, pip pulls the default
# wheel, which drags in CUDA packages worth several gigabytes that TraceRAG
# never uses.
COPY requirements.txt ./
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu \
      -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY evaluation ./evaluation
COPY data/corpus ./data/corpus
COPY reports ./reports
COPY pytest.ini ./

# Pre-download the embedding model so the image runs without network access.
ARG BAKE_MODEL=true
RUN if [ "$BAKE_MODEL" = "true" ]; then \
      python -c "from sentence_transformers import SentenceTransformer; \
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')" ; \
    fi

# Ingest the sample corpus at build time so the container is useful the moment
# it starts. The database lives on a volume in compose, which overlays this.
RUN python -m scripts.load_corpus --skip-index

# Run as a non-root user. The data directory and the model cache must be
# writable by it. HF_HOME is created explicitly: with BAKE_MODEL=false nothing
# has written to it yet, so it would not otherwise exist to be chowned, and the
# model download at first run would then fail on a read-only parent.
RUN mkdir -p /opt/hf-cache \
 && useradd --create-home --uid 10001 tracerag \
 && chown -R tracerag:tracerag /app /opt/hf-cache
USER tracerag

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
