FROM python:3.14-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    git \
    gettext \
    libpng-dev \
    libjpeg-dev \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install uv to a system-wide location (avoids /root/.local/bin dependency)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/uv

# Copy the manifest and the lock so this layer is cached on them alone
COPY pyproject.toml uv.lock ./

# Install exactly the locked dependency set, system-wide. Resolving fresh here
# made every rebuild drift: one with no commit behind it picked SQLAlchemy
# 2.1, whose default driver for `postgresql://` is psycopg3, and the backend
# refused to boot on `No module named 'psycopg'`. The lock is the set CI and
# the tests run against, so the image is built from the same one.
RUN uv export --frozen --no-dev --no-emit-project -o /tmp/requirements.txt && \
    uv pip install --system -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# Create non-root user to avoid running the app as root
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

# Copy application code
COPY . .

# Install the application itself editable, without re-resolving the pinned
# dependencies from the layer above (source is bind-mounted in dev, so the
# tests import the same tree the layers describe).
RUN uv pip install --system --no-deps -e .

# Make entrypoint executable, create uploads directory, transfer ownership
# data/ holds deployment state (the community-module tracking file). The
# production compose mounts a named volume there; creating and owning the
# directory here is what makes that volume writable by appuser on first use.
RUN chmod +x /app/entrypoint.sh && \
    mkdir -p uploads/temp logs data && \
    chown -R appuser:appuser /app

# Drop privileges — all app code runs as non-root from here
USER appuser

# Expose port
EXPOSE 8000

# Set entrypoint to run migrations before app starts
ENTRYPOINT ["/app/entrypoint.sh"]

# Run the application
# Workers: leave 2 cores for Redis + 2x PostgreSQL on the same VPS
# Override via WEB_CONCURRENCY env var (e.g. WEB_CONCURRENCY=8 on a dedicated server)
# --forwarded-allow-ips: trust X-Forwarded-For from the reverse proxy so
# request.client.host is the real client IP (rate limiting buckets per
# client). The default '*' rests on the backend port being reachable only on
# app-network; FORWARDED_ALLOW_IPS narrows it for a deployment where that is
# not true. A wrong list is silent — every request would bucket to the
# proxy's address, so one client's brute force spends everyone's limit.
# --config gunicorn.conf.py: routes the arbiter's own lines through the same
# log format as the app (it replaces --access-logfile/--error-logfile, which
# force gunicorn's format onto stdout).
CMD gunicorn app.main:app \
    --config gunicorn.conf.py \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers "${WEB_CONCURRENCY:-4}" \
    --bind 0.0.0.0:8000 \
    --timeout 300 \
    --graceful-timeout 30 \
    --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}"
