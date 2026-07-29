FROM python:3.13-slim

WORKDIR /app

# Install build dependencies for compiling native extensions (like hnswlib for ChromaDB)
RUN apt-get update && apt-get install -y build-essential g++ && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source and data
COPY src/ /app/src/
COPY data/raw/ /app/data/raw/

# Create chroma_db directory
RUN mkdir -p /app/data/chroma_db

# Expose port
EXPOSE 8000

# Start server (run ingestion first so it uses the GOOGLE_API_KEY env var)
CMD ["sh", "-c", "python src/ingest.py && uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload"]
