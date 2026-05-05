FROM python:3.11-slim

# Install system dependencies needed by some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python package `app` lives under ./backend; keep it importable as `app.*`
ENV PYTHONPATH=/app/backend

# Install Python dependencies (cached layer — only re-runs if requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Ensure shell scripts are executable
RUN chmod +x start_worker.sh start_flower.sh 2>/dev/null || true

CMD ["python", "migrate_and_start.py"]
