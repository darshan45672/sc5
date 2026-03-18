# Use official Python runtime as base image
FROM python:3.11-slim

# Set working directory in container
WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Copy requirements file from project root
COPY ../requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code from src directory
COPY ../src/api.py .
COPY ../src/assignment_group_mapping.yaml .
COPY ../src/.env .

# Expose port 5000
EXPOSE 5000

# Run the application
CMD ["python", "api.py"]
