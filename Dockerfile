# Cloud Run deploys this by building from the repo root (gcloud run deploy --source .
# or via a Cloud Build GitHub trigger). Only backend/ is needed in the image -- the
# frontend stays on Vercel and is never built here.
FROM python:3.12-slim

WORKDIR /app

# build-essential + libpq-dev are a safety net in case any dependency needs to compile
# from source on this platform; psycopg2-binary/Pillow normally ship prebuilt wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend backend

ENV PYTHONUNBUFFERED=1
ENV SERVER_MEMORY_LIMIT_MB=2048
ENV UPLOAD_CONCURRENCY=32
ENV UPLOAD_SLOTS=64
ENV STREAM_COPY_CHUNK=2097152
ENV VISION_CONCURRENCY=12
ENV TAG_CONCURRENCY=8
ENV CHUNK_CONCURRENCY=8
ENV BIG_DECODE_CONCURRENCY=6
ENV MALLOC_ARENA_MAX=4
EXPOSE 8080

# Cloud Run injects $PORT (defaults to 8080); single worker -- see .env.example, the
# upload queue's advisory lock and in-process state assume one process per container.
CMD exec uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8080}
