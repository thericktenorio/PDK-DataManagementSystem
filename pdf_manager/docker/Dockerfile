# MULTI-STAGE DOCKERFILE

# ==============
# 1. BUILDER STAGE
# ==============
FROM python:3.10-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt constraints.txt ./
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install -r requirements.txt -c constraints.txt


# ==============
# 2. RUNTIME STAGE
# ==============
FROM python:3.10-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:$PATH" \
    DATA_ROOT="/home/app/data"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    libjpeg62-turbo \
    zlib1g \
    libpng16-16 \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user ONCE
RUN groupadd -r app && useradd -r -g app app && \
    mkdir -p /home/app && chown -R app:app /home/app

COPY --from=builder /opt/venv /opt/venv
COPY . /app/

# Create data dirs inside image (helps even without volume)
RUN mkdir -p /home/app/data/incoming /home/app/data/outputs /home/app/data/reports && \
    chown -R app:app /home/app /app && \
    chmod +x /app/docker/entrypoint.sh

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "pdf_manager.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
