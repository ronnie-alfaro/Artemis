FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml .
COPY app ./app
RUN pip install --no-cache-dir --prefix=/install . --extra-index-url https://download.pytorch.org/whl/cpu

FROM python:3.12-slim
ENV ARTEMIS_EMBEDDING_MODEL_PATH=/opt/models/all-MiniLM-L6-v2
ENV ARTEMIS_EMBEDDINGS_OFFLINE=true
ENV HF_HUB_OFFLINE=1
RUN useradd --system --uid 10001 artemis
WORKDIR /app
COPY --from=builder /install /usr/local
COPY app ./app
RUN HF_HUB_OFFLINE=0 python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2', device='cpu').save('/opt/models/all-MiniLM-L6-v2')"
RUN mkdir -p /data/memory && chown artemis /data/memory
RUN chmod -R a+rX /app/app /opt/models
USER artemis
EXPOSE 8000
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
