# Use standard Python image for production (no slim/alpine to avoid build issues with C-extensions like asyncpg/Playwright)
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies using standard pip
# In a real environment, you might use a lockfile or hatch directly, 
# but for this foundation we use standard pip with the project file.
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Copy project files
COPY src/ ./src/
COPY migrations/ ./migrations/
COPY alembic.ini .

# Expose port
EXPOSE 8080

# Command to run the application (optimized for Cloud Run)
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
