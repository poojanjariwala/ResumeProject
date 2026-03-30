FROM python:3.10-slim

# This ensures Python finds your modules correctly
ENV PYTHONPATH=/app

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements from your local 'app' folder to the container's root
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# CRITICAL CHANGE: Copy the CONTENTS of your local 'app' folder 
# directly into the container's /app WORKDIR
COPY app/ .

# Create the data directory
RUN mkdir -p /app/data

# Now main.py is in the root of /app, so we run it directly
CMD ["python", "main.py"]
