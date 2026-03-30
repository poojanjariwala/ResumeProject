FROM python:3.10-slim

# This is the "Magic" line that fixes the ModuleNotFoundError
ENV PYTHONPATH=/

WORKDIR /app

# Install dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements from your local 'app' folder
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the ENTIRE project into the container's /app directory
COPY . .

# Create data directory
RUN mkdir -p /app/data

# Run the app directly from the /app directory
CMD ["python", "app/main.py"]
