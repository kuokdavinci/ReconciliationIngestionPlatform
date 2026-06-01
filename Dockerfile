FROM python:3.11-slim

WORKDIR /app

# Install system dependencies needed for some Python packages (like paramiko, cryptography, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject.toml and build files if setuptools is used
COPY pyproject.toml ./
COPY requirements.txt ./

# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir "APScheduler>=3.10" "httpx>=0.27" "watchdog>=4.0" "paramiko>=5.0.0"

# Copy the rest of the application
COPY src/ ./src
COPY run.py ./

# Create default directories
RUN mkdir -p downloads tmp_downloads sftp_data

CMD ["python", "run.py", "--start-scheduler"]
