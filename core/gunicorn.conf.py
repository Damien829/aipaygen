"""Gunicorn configuration for AiPayGen.

Background jobs never run in these workers; run_scheduler.py is the one job process.
"""
import os

workers = int(os.getenv("WEB_WORKERS", "2"))
worker_class = "gthread"
threads = int(os.getenv("WEB_THREADS", "4"))
bind = os.getenv("WEB_BIND", "127.0.0.1:5001")
timeout = 120
keepalive = 75
max_requests = 300       # Recycle workers more often to prevent memory bloat
max_requests_jitter = 30
preload_app = False
accesslog = "-"          # stdout, collected by the container runtime
errorlog = "-"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s %(T)sms "%(f)s" "%(a)s"'
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1")
