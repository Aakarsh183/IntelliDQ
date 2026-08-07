# syntax=docker/dockerfile:1
#
# IntelliDQ backend - FastAPI + PySpark, served by uvicorn.
#
# Build from the REPO ROOT (the context must include backend/):
#   docker build -t intellidq-backend:local .
#
# The container needs Azure credentials to even start: main_app.py constructs a
# GrokClient() at import, whose __init__ builds an AzureOpenAI client, and the openai
# SDK raises when api_key or azure_endpoint is missing. Pass them or it exits instantly:
#   docker run --rm -p 8000:8000 --env-file .env intellidq-backend:local

########################  builder  ########################
FROM python:3.11-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Everything installs into a venv that the runtime stage copies wholesale, so pip's
# metadata and any transient build tooling never reach the final image.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/requirements.txt /tmp/requirements.txt

# column_resolver.py imports sentence_transformers at module scope, so torch is required
# just to import the app. The default PyPI wheel bundles CUDA (~2.5 GB) and nothing here
# uses a GPU - install the CPU wheel first so the resolver sees torch as satisfied.
#
# If you later pin versions into backend/requirements.lock.txt, install that here instead.
RUN pip install --upgrade pip \
 && pip install --index-url https://download.pytorch.org/whl/cpu torch \
 && pip install -r /tmp/requirements.txt

########################  runtime  ########################
FROM python:3.11-slim-bookworm AS runtime

# PySpark needs a JVM and python:slim ships none. jre-headless is ~180 MB against ~450 MB
# for a full JDK, and nothing here compiles Java. curl backs the HEALTHCHECK below.
#
# The symlink derives JAVA_HOME from whatever java actually got installed, so this does
# not break on arm64 (where the path is java-17-openjdk-arm64, not -amd64).
RUN apt-get update \
 && apt-get install -y --no-install-recommends openjdk-17-jre-headless curl \
 && rm -rf /var/lib/apt/lists/* \
 && ln -sfn "$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")" /usr/lib/jvm/default-java

ENV JAVA_HOME=/usr/lib/jvm/default-java \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# backend/ contents land at /app itself, NOT /app/backend. main_app.py uses flat imports
# (`from grok_client import GrokClient`), so its siblings must sit directly on sys.path.
COPY backend/ /app/

# Non-root: a few lines that remove an entire severity class from any container escape.
# .session_store and dq_checks.py are written at runtime, so /app must stay writable by
# this user - see the volume note in docker-compose.yml about persisting them.
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /app/.session_store \
 && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# start-period is generous on purpose: importing main_app pulls in torch, transformers
# and pyspark, which takes tens of seconds on a cold container.
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD curl -fsS http://localhost:8000/docs || exit 1

CMD ["python", "-m", "uvicorn", "main_app:app", "--host", "0.0.0.0", "--port", "8000"]
