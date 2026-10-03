FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# System deps for pyswisseph (gcc/g++ needed to compile C extension)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CACHEBUST=3 — increment this to force Railway to re-run pip install
ARG CACHEBUST=3
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the ONNX embedding model so Railway startup is instant.
# fastembed caches the model in ~/.cache/fastembed on first embed() call.
RUN python -c "\
from fastembed import TextEmbedding; \
list(TextEmbedding('sentence-transformers/all-MiniLM-L6-v2').embed(['warmup'])); \
print('fastembed model cached')"

COPY . .

# Create data dirs
RUN mkdir -p data/chroma books

EXPOSE 8000

CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1