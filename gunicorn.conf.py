"""Gunicorn configuration for AiPayGen."""
workers = 2          # Reduced from 4 — saves ~300MB RAM, sufficient for current traffic
worker_class = "gthread"
threads = 4
bind = "127.0.0.1:5001"
timeout = 120
keepalive = 75
max_requests = 300       # Recycle workers more often to prevent memory bloat
max_requests_jitter = 30
preload_app = False  # Disabled to allow template hot-reload
accesslog = "/home/damien809/agent-service/access.log"
errorlog = "/home/damien809/agent-service/agent.log"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s %(T)sms "%(f)s" "%(a)s"'
