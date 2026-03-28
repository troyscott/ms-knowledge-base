FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir ".[azure]"

COPY src/ src/
COPY config/ config/
COPY scripts/ scripts/

# Pre-download embedding model at build time (not at runtime)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Data and content live on named volumes — persist across rebuilds
VOLUME ["/app/data", "/app/content"]

EXPOSE 3200

CMD ["python", "-m", "ms_knowledge_base.server.main", \
     "--transport", "sse", \
     "--host", "0.0.0.0", \
     "--port", "3200", \
     "--auth", "none"]
