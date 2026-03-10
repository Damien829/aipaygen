"""Gunicorn configuration for AiPayGen."""
workers = 2
worker_class = "sync"
bind = "127.0.0.1:5001"
timeout = 120
keepalive = 5
max_requests = 1000
max_requests_jitter = 50
accesslog = "/home/damien809/agent-service/access.log"
errorlog = "/home/damien809/agent-service/agent.log"
loglevel = "info"
