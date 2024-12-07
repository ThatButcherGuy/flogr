FROM python:3.11-slim-bookworm

# Create the 'apps' user and group with UID 568 and GID 568
RUN groupadd -g 568 apps && \
    useradd -u 568 -g apps apps

# Set the working directory
WORKDIR /flask-app

# Copy the requirements file and install dependencies
COPY requirements.txt requirements.txt
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    build-essential && \
    pip3 install --no-cache-dir -r requirements.txt && \
    apt-get remove -y build-essential python3-dev gcc && \
    apt-get autoremove -y && apt-get clean && find . -name "__pycache__" -type d -exec rm -r {} +

# Copy the application code (including static, templates, and data directories)
COPY . .

# Ensure the application and data directories exist and set proper permissions
RUN mkdir -p /flask-app/data && \
    touch /flask-app/data/flogr.db && \
    chown -R apps:apps /flask-app

# Switch to the 'apps' user for running the app
USER apps

# Command to run the app using Gunicorn
CMD ["gunicorn", "--config", "gunicorn_config.py", "app:app"]
