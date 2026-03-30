FROM python:3.10-slim

WORKDIR /app

# Install system dependencies required for parsing PDFs and DOCX etc.
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create a data directory for uploading files to share between API and Worker
RUN mkdir -p /app/data
CMD ["python", "app/main.py"]
