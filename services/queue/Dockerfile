FROM python:3.10-slim-bookworm AS base

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    MINERU_API_URL=http://host.docker.internal:8401 \
    MINERU_QUEUE_TMP_DIR=/tmp/mineru-queue \
    MINERU_QUEUE_OUTPUT_ROOT=/app/output \
    MINERU_QUEUE_DB_PATH=/app/output/mineru_queue.db

FROM base AS build

# Configure Chinese mirrors for bookworm (uses sources.list.d)
RUN if [ -f /etc/apt/sources.list ]; then \
       sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list; \
     elif [ -d /etc/apt/sources.list.d ]; then \
       for f in /etc/apt/sources.list.d/*.sources; do \
         [ -f "$f" ] && sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' "$f"; \
       done; \
     fi

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m venv /app/venv && \
    . /app/venv/bin/activate && \
    pip install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

FROM base AS prod

# Configure Chinese mirrors for bookworm (uses sources.list.d)
RUN if [ -f /etc/apt/sources.list ]; then \
       sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list; \
     elif [ -d /etc/apt/sources.list.d ]; then \
       for f in /etc/apt/sources.list.d/*.sources; do \
         [ -f "$f" ] && sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' "$f"; \
       done; \
     fi

COPY --from=build /app/venv /app/venv

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgomp1 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create directories
RUN mkdir -p /tmp/mineru-queue /app/output
VOLUME [ "/tmp/mineru-queue", "/app/output" ]

# Copy application code into a package (named mineru_queue to avoid stdlib 'queue' conflict)
RUN mkdir -p /app/mineru_queue
COPY __init__.py app.py consumer.py models.py sqlite_queue.py /app/mineru_queue/

# Copy entrypoint
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8403

ENTRYPOINT [ "/app/entrypoint.sh" ]