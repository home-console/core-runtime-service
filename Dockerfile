# Single-stage build для Core Runtime
FROM python:3.13-slim

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt requirements.lock* ./
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    if [ -f requirements.lock ]; then pip install --no-cache-dir -r requirements.lock; else pip install --no-cache-dir -r requirements.txt; fi

# Copy application code
COPY . .

# Скрипты операций должны быть в образе (hc secrets exec → secrets_tool.py)
RUN test -f scripts/secrets_tool.py || (echo "MISSING scripts/secrets_tool.py — проверь .dockerignore" && exit 1)

# Create data directory для SQLite (если нужно)
RUN mkdir -p /data && chown -R nobody:nogroup /data

# Health check
HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/monitor/health || exit 1

# Switch to non-root user
USER nobody

# Expose port
EXPOSE 8000

# Default environment
ENV LOG_LEVEL=INFO
ENV DEBUG=false

# Run application
CMD ["python", "main.py"]
