#!/bin/bash
# Check pipeline daemon status

cd "$(dirname "$0")/.."

if [ -f .pipeline.pid ]; then
    PID=$(cat .pipeline.pid)
    if ps -p $PID > /dev/null 2>&1; then
        echo "✓ Pipeline daemon is running"
        echo "  PID: $PID"
        echo "  Log file: logs/pipeline.log"
        echo "  PID file: .pipeline.pid"
        echo ""
        echo "To stop: ./scripts/stop_pipeline.sh"
        exit 0
    else
        echo "✗ Pipeline daemon is not running (stale PID file)"
        rm .pipeline.pid
        exit 1
    fi
else
    echo "✗ Pipeline daemon is not running"
    echo ""
    echo "To start: ./scripts/start_pipeline.sh"
    exit 1
fi
