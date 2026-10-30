FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LIFE_INBOX_ENV=beta \
    LIFE_INBOX_UPLOAD_DIR=/data/uploads \
    FASTEMBED_CACHE_PATH=/opt/fastembed

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the embedding model into the image so the first request does not need
# network access. If this step fails the build fails; the app itself would
# otherwise degrade to keyword search at runtime.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"

COPY . .

RUN mkdir -p /data/uploads

EXPOSE 8000

# Ready once migrations have run and the app answers; /healthz returns 503 if
# the database is unreachable or the schema is behind this build.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"

CMD ["sh", "-c", "python -m alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"]
