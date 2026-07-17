# ── Stage 1: Build C binary ──
FROM python:3.10-slim AS builder
RUN apt-get update --fix-missing && \
    apt-get install -y --no-install-recommends gcc make libc6-dev && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY app/pipeline/c_cleaner/ ./app/pipeline/c_cleaner/
RUN cd app/pipeline/c_cleaner && make clean && make

# ── Stage 2: Runtime ──
FROM python:3.10-slim
WORKDIR /app

# Copy requirements first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Copy compiled C binary (overwriting source bin if any)
COPY --from=builder /build/app/pipeline/c_cleaner/bin/ ./app/pipeline/c_cleaner/bin/

# Create data directories
RUN mkdir -p data/raw data/cleaned data/ner data/semantic data/chapters data/summaries data/tmp_ollama

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
