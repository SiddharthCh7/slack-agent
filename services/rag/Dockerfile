FROM python:3.11-slim

WORKDIR /app

# Install uv
RUN pip install uv --no-cache-dir

# Copy project definition first (layer cache)
COPY pyproject.toml .

# Install dependencies with uv (no venv needed inside container)
RUN uv pip install --system --no-cache -r pyproject.toml 2>/dev/null || \
    uv pip install --system --no-cache \
        fastapi uvicorn[standard] fastmcp qdrant-client \
        sentence-transformers einops pydantic python-dotenv httpx

# Copy source
COPY . .

# Expose port
EXPOSE 7070

# Health check — waits up to 120s for model to warm
HEALTHCHECK --interval=10s --timeout=5s --start-period=120s --retries=12 \
    CMD python -c "import httpx; r=httpx.get('http://localhost:7070/health'); exit(0 if r.json().get('ready') else 1)"

CMD ["python", "server.py"]
