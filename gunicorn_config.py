import os
import multiprocessing

# Worker and thread settings
#workers = int(os.environ.get('GUNICORN_PROCESSES', '2'))
workers = int(os.environ.get('GUNICORN_PROCESSES', multiprocessing.cpu_count() * 2 + 1))
threads = int(os.environ.get('GUNICORN_THREADS', '4'))

# Timeout settings
timeout = int(os.environ.get('GUNICORN_TIMEOUT', '120'))
graceful_timeout = int(os.environ.get('GUNICORN_GRACEFUL_TIMEOUT', '30'))

# Binding
bind = os.environ.get('GUNICORN_BIND', '0.0.0.0:8080')

# Logging
accesslog = '-'  # Log access requests to stdout
errorlog = '-'   # Log errors to stderr
loglevel = os.environ.get('GUNICORN_LOG_LEVEL', 'info')

# Restart workers after handling a certain number of requests
max_requests = int(os.environ.get('GUNICORN_MAX_REQUESTS', '1000'))
max_requests_jitter = int(os.environ.get('GUNICORN_MAX_REQUESTS_JITTER', '50'))

# Reverse proxy headers
forwarded_allow_ips = '*'
secure_scheme_headers = {'X-Forwarded-Proto': 'https'}
