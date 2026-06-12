FROM python:3.12-slim

# Install git (required by Aider and sandbox operations)
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first to leverage Docker layer caching
COPY requirements.txt .

# Install dependencies (cached unless requirements.txt changes)
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose the default port
EXPOSE 8000

# Set PYTHONPATH so that app/main.py resolved modules correctly
ENV PYTHONPATH=/app

# Start the application
CMD ["python", "-m", "app.main"]
