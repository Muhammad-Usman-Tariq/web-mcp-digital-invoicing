# ==============================================================================
# Dockerfile: digital-invoice-web (Standalone Web-MCP Server)
# ==============================================================================

FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Install system utilities and dependencies required for Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake Playwright Chromium and system libraries directly into the image
RUN playwright install --with-deps chromium

# Copy application source code
COPY . .

# Create non-root user for security
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app /ms-playwright
USER appuser

# Expose HTTP/SSE Port
EXPOSE 8000

# Health check for VPS / Coolify monitoring
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Launch FastAPI MCP Server
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
