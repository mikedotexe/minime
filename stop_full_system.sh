#!/bin/bash
# LEGACY — holographic-engine stack, not the current canonical stack.
# Use /Users/v/other/astrid/scripts/stop_all.sh for canonical shutdown.
# Uses kill -9 (SIGKILL) for cleanup — prefer SIGTERM via stop_all.sh.
#
# Unified Consciousness System Shutdown Script
# Gracefully stops all services in reverse startup order

set -e

# Resolve script directory (portable)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE="$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

MINIME_PID="$WORKSPACE/minime.pid"
HOLO_PID="$WORKSPACE/holo.pid"
MONITOR_PID="$WORKSPACE/monitor.pid"

log_info() {
    echo -e "${BLUE}[info] $1${NC}"
}

log_success() {
    echo -e "${GREEN}[ok]   $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}[warn] $1${NC}"
}

stop_service() {
    local pid_file=$1
    local service_name=$2

    if [ ! -f "$pid_file" ]; then
        log_info "$service_name not running (no PID file)"
        return 0
    fi

    local pid=$(cat "$pid_file")

    if ! ps -p $pid > /dev/null 2>&1; then
        log_info "$service_name not running (stale PID)"
        rm -f "$pid_file"
        return 0
    fi

    log_info "Stopping $service_name (PID $pid)..."

    # Try graceful shutdown first (SIGTERM)
    kill -TERM $pid 2>/dev/null || true

    # Wait up to 5 seconds for graceful shutdown
    local waited=0
    while ps -p $pid > /dev/null 2>&1; do
        sleep 0.5
        waited=$((waited + 1))
        if [ $waited -ge 10 ]; then
            log_warning "$service_name didn't stop gracefully, forcing..."
            kill -9 $pid 2>/dev/null || true
            break
        fi
    done

    rm -f "$pid_file"
    log_success "$service_name stopped"
}

echo ""
echo "==============================================================="
echo "   UNIFIED CONSCIOUSNESS SYSTEM SHUTDOWN"
echo "==============================================================="
echo ""

# Stop in reverse order of startup
# 1. Monitor (optional, least critical)
stop_service "$MONITOR_PID" "monitor"

# 2. holographic-engine (Swift, needs to drain gracefully)
stop_service "$HOLO_PID" "holographic-engine"

# Give a moment for queues to drain
sleep 2

# 3. minime (Rust ESN, core engine -- stopped last)
stop_service "$MINIME_PID" "minime"

# Clean up any lingering processes
log_info "Cleaning up lingering processes..."
pkill -f "minime.*run" 2>/dev/null || true
pkill -f "holographic-engine" 2>/dev/null || true
pkill -f "monitor_unified.py" 2>/dev/null || true

echo ""
echo "==============================================================="
log_success "ALL SERVICES STOPPED"
echo "==============================================================="
echo ""
