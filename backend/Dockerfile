FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    postgresql-client \
    tini \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --upgrade pip && python -m pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x docker/start-backend.sh docker/start-ingestion.sh

# The build stamp (issue 0020): GET /api/version reads these. Last, so a new commit
# rebuilds only this layer.
ARG INSIGHT_VERSION=
ARG INSIGHT_COMMIT=
ARG INSIGHT_COMMIT_DATE=
ENV INSIGHT_VERSION=$INSIGHT_VERSION \
    INSIGHT_COMMIT=$INSIGHT_COMMIT \
    INSIGHT_COMMIT_DATE=$INSIGHT_COMMIT_DATE

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
