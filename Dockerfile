# Single-stage build для Core Runtime
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory для SQLite (если нужно)
RUN mkdir -p /data && chown -R nobody:nogroup /data

# Health check
HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/admin/v1/status || exit 1

# Switch to non-root user
USER nobody

# Expose port
EXPOSE 8000

# Default environment
ENV LOG_LEVEL=INFO
ENV DEBUG=false

# Run application
CMD ["python", "main.py"]
