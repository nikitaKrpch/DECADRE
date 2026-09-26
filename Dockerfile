# Use the official slim Python 3.9 base image
FROM python:3.9-slim

# Install system dependencies (e.g., for spaCy or packages with C extensions)
RUN apt-get update && apt-get install -y gcc g++ build-essential && rm -rf /var/lib/apt/lists/*

# Set working directory inside the container
WORKDIR /app

# Copy dependency file and install Python packages
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy all remaining application files
COPY . .

# Expose the port your Flask/Gunicorn app will listen on
EXPOSE 5000

# Start the app using Gunicorn with 4 worker processes
CMD ["gunicorn", "-w", "1", "--threads", "4", "-b", "0.0.0.0:5000", "--timeout", "0", "app:app"]
