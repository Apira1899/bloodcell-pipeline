# Build from the REPOSITORY ROOT so the model folder is in the context:
#   docker build -f api/Dockerfile -t bloodcell-api:1.0.0 .

# ---------- Stage 1: install dependencies into a virtualenv ----------
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY api/requirements.txt .
RUN pip install -r requirements.txt

# ---------- Stage 2: minimal runtime image ----------
FROM python:3.12-slim
ARG MODEL_VERSION=1.0.0
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MODEL_VERSION=${MODEL_VERSION} \
    MODEL_PATH=/app/model/model-${MODEL_VERSION}.onnx \
    LABELS_PATH=/app/model/labels.json \
    PORT=8000

RUN useradd --create-home --uid 10001 appuser
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=appuser:appuser api/app ./app
COPY --chown=appuser:appuser model/model-${MODEL_VERSION}.onnx model/labels.json ./model/

USER appuser
EXPOSE 8000

# python:slim has no curl -> use Python for the health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health', timeout=4)" || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
