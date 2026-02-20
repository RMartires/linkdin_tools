#!/bin/bash
# Stop the pipeline daemon

cd "$(dirname "$0")/.."

if [ ! -f .pipeline.pid ]; then
    echo "Pipeline daemon is not running (no PID file found)"
    exit 1
fi

PID=$(cat .pipeline.pid)

if ps -p $PID > /dev/null 2>&1; then
    echo "Stopping pipeline daemon (PID: $PID)..."
    kill $PID
    
    # Wait for graceful shutdown
    for i in {1..10}; do
        if ! ps -p $PID > /dev/null 2>&1; then
            break
        fi
        sleep 0.5
    done
    
    # Force kill if still running
    if ps -p $PID > /dev/null 2>&1; then
        echo "Force killing daemon..."
        kill -9 $PID
    fi
    
    rm .pipeline.pid
    echo "✓ Pipeline daemon stopped"
else
    echo "Pipeline daemon is not running (stale PID file)"
    rm .pipeline.pid
    exit 1
fi
