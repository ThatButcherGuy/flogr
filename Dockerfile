FROM python:3.11-slim-bookworm

# Create the 'apps' user and group with UID 568 and GID 568
RUN groupadd -g 568 apps && \
    useradd -u 568 -g apps apps

# Set the working directory
WORKDIR /flask-app

# Copy the requirements file and install dependencies
COPY requirements.txt requirements.txt

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    build-essential \
  && python -m pip install --upgrade pip setuptools==84.0.0 wheel \
  && pip3 install --no-cache-dir -r requirements.txt \
  && apt-get remove -y build-essential python3-dev gcc \
  && apt-get autoremove -y \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/* /root/.cache/pip

# Copy the application code (including static, templates, and data directories)
COPY . .

# Ensure the application directory exists and set ownership in the image
RUN mkdir -p /flask-app/data && \
    chown -R apps:apps /flask-app

# Switch to the 'apps' user for running the app
USER apps

# Command to run the app using Gunicorn
CMD ["gunicorn", "--config", "gunicorn_config.py", "app:app"]
