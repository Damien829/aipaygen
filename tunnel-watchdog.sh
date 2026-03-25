#!/bin/bash
# Tunnel watchdog - restarts tunnel if it's dead or site is unreachable
TUNNEL_SERVICE="aipaygent-tunnel"
APP_SERVICE="aipaygent"

# Check if tunnel process exists
if ! pgrep -f cloudflared > /dev/null 2>&1; then
    echo "$(date): Tunnel dead, restarting" >> /home/damien809/agent-service/watchdog.log
    sudo systemctl restart $TUNNEL_SERVICE
fi

# Check if app is responding locally
if ! curl -sf http://localhost:5001/health > /dev/null 2>&1; then
    echo "$(date): App not responding, restarting" >> /home/damien809/agent-service/watchdog.log
    sudo systemctl restart $APP_SERVICE
    sleep 5
    sudo systemctl restart $TUNNEL_SERVICE
fi
