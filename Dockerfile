# Digest-pinned (multi-arch index, 2026-08-16): a mutable tag repoints when
# the maintainer pushes — same supply-chain hole SHA-pinning closed for
# Actions. tools/validate_ci.py enforces digest pinning on every FROM.
FROM python:3.14-slim@sha256:cae66f2ef0ec51a9891263eeee7f987dacf0a9879e8aa9353d5606e0530619a5

# Install system dependencies needed by some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python package `app` lives under ./backend; keep it importable as `app.*`
ENV PYTHONPATH=/app/backend

# Install Python dependencies (cached layer — only re-runs if the lock changes).
# Hash-locked: scorecard PinnedDependencies accepts only --require-hashes
# installs, and hashes make image builds reproducible. Regenerate
# requirements-lock.txt with tools/gen_dependency_lock.py after bumping
# requirements.txt.
COPY requirements-lock.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements-lock.txt
RUN python -m playwright install --with-deps chromium

# Copy the rest of the application
COPY . .

# Ensure shell scripts are executable
RUN chmod +x start_worker.sh start_flower.sh 2>/dev/null || true

CMD ["python", "migrate_and_start.py"]
