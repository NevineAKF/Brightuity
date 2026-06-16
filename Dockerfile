# Brightuity — single shared image for all Python services.
# Each container specifies its own command via docker-compose; this image
# provides a complete, reproducible runtime with the RAG embedding model
# baked in (no HuggingFace downloads at runtime).
#
# Build:  docker build -t brightuity .
# Run:    docker-compose up          (preferred)
#         docker run brightuity      (prints usage hint)
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

WORKDIR /app

ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Embedding model cache — baked at build time, used read-only at runtime.
    HF_HOME=/app/.cache/huggingface \
    # Suppress HuggingFace progress bars and analytics inside the container.
    HF_HUB_DISABLE_PROGRESS_BARS=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    TOKENIZERS_PARALLELISM=false

# Runtime shared libraries needed by:
#   torch        → libgomp1 (OpenMP threading)
#   cryptography → libssl3, libffi8 (C bindings for OpenSSL/libffi)
#   networking   → ca-certificates
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        libgomp1 \
        libssl3 \
        libffi8 \
        ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# ── Dependency layer ──────────────────────────────────────────────────────────
# Copied first so this expensive layer is cached until requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# ── Embedding model — baked into image at build time ─────────────────────────
# Model: all-MiniLM-L6-v2 (~90 MB), stored under HF_HOME above.
# agents/dynamic_compliance/retrieval.py:24 and rag_corpus/build_index.py:34
# both reference this exact model name — grep for _EMBEDDING_MODEL to confirm.
# This RUN layer is cached until the pip layer above changes.
RUN python -c "\
from sentence_transformers import SentenceTransformer; \
print('Baking embedding model all-MiniLM-L6-v2 ...'); \
SentenceTransformer('all-MiniLM-L6-v2'); \
print('Model baked successfully.')"

# ── Application source ────────────────────────────────────────────────────────
# Copied last: code changes invalidate only this layer, not deps or the model.
COPY . .

# Build the ChromaDB regulatory RAG index from the committed corpus.
# Offline: embedding model (all-MiniLM-L6-v2) already in HF_HOME from the layer above.
# Output: /app/rag_corpus/chroma_index/  (sub-10s, ~841KB; gitignored so must be built here)
RUN python rag_corpus/build_index.py

# ── No single-service CMD ─────────────────────────────────────────────────────
# docker-compose sets the command per container (see docker-compose.yml).
# Running the bare image without a compose override prints a usage hint.
#
# Available entry points (run with: python -m <entry_point>):
#   backend.main                      — FastAPI gateway  (port 8000)
#   band_agents.run_orchestrator_agent — Band orchestrator
#   band_agents.run_kyc_agent          — KYC Guardian
#   band_agents.run_compliance_agent   — Dynamic Compliance
#   band_agents.run_docauditor_agent   — Doc Auditor
#   band_agents.run_stresstest_agent   — Stress Test
#   band_agents.run_tokenizer_agent    — Asset Tokenizer
CMD ["python", "-c", "\
print('Brightuity container — no default service configured.'); \
print('Specify a command in docker-compose.yml or via --command.'); \
print(); \
print('Entry points (python -m <name>):'); \
print('  backend.main                       FastAPI gateway  (port 8000)'); \
print('  band_agents.run_orchestrator_agent Band orchestrator'); \
print('  band_agents.run_kyc_agent          KYC Guardian'); \
print('  band_agents.run_compliance_agent   Dynamic Compliance'); \
print('  band_agents.run_docauditor_agent   Doc Auditor'); \
print('  band_agents.run_stresstest_agent   Stress Test'); \
print('  band_agents.run_tokenizer_agent    Asset Tokenizer'); \
"]
