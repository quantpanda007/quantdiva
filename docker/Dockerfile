FROM python:3.11-slim

WORKDIR /app

# System dependencies for QuantLib
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libboost-all-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[all]" || pip install --no-cache-dir QuantLib-Python numpy scipy pandas pydantic fastapi uvicorn redis sqlalchemy

# Copy application code
COPY . .

# Expose ports
EXPOSE 8000 8501

# Default: run the API server
CMD ["uvicorn", "api.fastapi.app:app", "--host", "0.0.0.0", "--port", "8000"]
