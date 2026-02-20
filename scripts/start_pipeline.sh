#!/bin/bash
# Start the pipeline daemon

cd "$(dirname "$0")/.."

# Check if already running
if [ -f .pipeline.pid ]; then
    PID=$(cat .pipeline.pid)
    if ps -p $PID > /dev/null 2>&1; then
        echo "Pipeline daemon is already running (PID: $PID)"
        exit 1
    else
        echo "Removing stale PID file"
        rm .pipeline.pid
    fi
fi

# Ensure logs directory exists
mkdir -p logs

# Start daemon (nohup prevents SIGHUP from killing process when shell exits)
echo "Starting pipeline daemon..."
nohup python3 scripts/pipeline_daemon.py >> logs/pipeline.log 2>&1 &
DAEMON_PID=$!

# Wait a moment for daemon to start and write its own PID file
sleep 2

if ps -p $DAEMON_PID > /dev/null 2>&1; then
    echo "✓ Pipeline daemon started (PID: $DAEMON_PID)"
    echo "  Log file: logs/pipeline.log"
    echo "  PID file: .pipeline.pid"
    echo ""
    echo "To stop: ./scripts/stop_pipeline.sh"
    echo "To check status: ./scripts/status_pipeline.sh"
else
    echo "✗ Failed to start pipeline daemon"
    echo "Check logs/pipeline.log for details"
    exit 1
fi
