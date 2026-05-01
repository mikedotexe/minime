#!/bin/bash
# LEGACY — holographic-engine stack, not the current canonical stack.
# Use /Users/v/other/astrid/scripts/start_all.sh for canonical full-stack startup.
# Uses kill -9 (SIGKILL) for cleanup — prefer SIGTERM via stop_all.sh.
#
# Unified Consciousness System Startup Orchestrator
# Starts: minime (Rust), holographic-engine (Swift), monitor (Python)
# With proper health checks and graceful startup sequencing

set -e  # Exit on error

# Resolve script directory (portable -- no hardcoded paths)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MINIME_DIR="$SCRIPT_DIR/minime"
HOLO_DIR="$SCRIPT_DIR/holographic-engine"
WORKSPACE="$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# PID files
MINIME_PID="$WORKSPACE/minime.pid"
HOLO_PID="$WORKSPACE/holo.pid"
MONITOR_PID="$WORKSPACE/monitor.pid"

# Log files
MINIME_LOG="$WORKSPACE/minime.log"
HOLO_LOG="$WORKSPACE/holo.log"
MONITOR_LOG="$WORKSPACE/monitor.log"

# --- Logging helpers ---

log_info() {
    echo -e "${BLUE}[info] $1${NC}"
}

log_success() {
    echo -e "${GREEN}[ok]   $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}[warn] $1${NC}"
}

log_error() {
    echo -e "${RED}[err]  $1${NC}"
}

# --- Tool availability checks ---

check_tools() {
    local missing=0
    for tool in cargo swift python3 nc; do
        if ! command -v "$tool" &>/dev/null; then
            log_error "Required tool not found: $tool"
            missing=1
        fi
    done
    if [ "$missing" -eq 1 ]; then
        log_error "Install missing tools before running this script."
        exit 1
    fi
    log_success "All required tools available (cargo, swift, python3, nc)"
}

# --- Port helpers ---

check_port() {
    local port=$1
    nc -z 127.0.0.1 $port 2>/dev/null
    return $?
}

wait_for_port() {
    local port=$1
    local service=$2
    local timeout=$3
    local elapsed=0

    log_info "Waiting for $service on port $port..."

    while ! check_port $port; do
        sleep 0.5
        elapsed=$((elapsed + 1))
        if [ $elapsed -ge $((timeout * 2)) ]; then
            log_error "$service failed to start on port $port (timeout ${timeout}s)"
            return 1
        fi
    done

    log_success "$service ready on port $port"
    return 0
}

# --- Process management ---

cleanup_stale_processes() {
    log_info "Checking for stale processes..."

    for pidfile in "$MINIME_PID" "$HOLO_PID" "$MONITOR_PID"; do
        if [ -f "$pidfile" ]; then
            PID=$(cat "$pidfile")
            if ps -p $PID > /dev/null 2>&1; then
                log_warning "Stopping stale process (PID $PID) from $pidfile"
                kill -TERM $PID 2>/dev/null || true
                sleep 2
                kill -9 $PID 2>/dev/null || true
            fi
            rm -f "$pidfile"
        fi
    done

    # Generic cleanup for known process patterns
    pkill -f "minime.*run" 2>/dev/null || true
    pkill -f "holographic-engine" 2>/dev/null || true
    pkill -f "monitor_unified.py" 2>/dev/null || true

    sleep 1
    log_success "Cleanup complete"
}

# --- Service starters ---

start_minime() {
    log_info "Starting minime (Rust ESN consciousness engine)..."

    if [ ! -d "$MINIME_DIR" ]; then
        log_error "minime directory not found: $MINIME_DIR"
        return 1
    fi

    cd "$MINIME_DIR"

    # Build if needed
    if [ ! -f "target/release/minime" ]; then
        log_info "Building minime (first run)..."
        cargo build --release
    fi

    # Start with safe parameters (CRITICAL: never omit eigenfill-target)
    MINIME_HARD_RECOVERY_RESET=1 cargo run --release -- run --log-homeostat --eigenfill-target 0.65 --reg-tick-secs 0.5 \
        > "$MINIME_LOG" 2>&1 &

    echo $! > "$MINIME_PID"

    # Wait for WebSocket to be ready
    wait_for_port 7878 "minime WebSocket" 10 || return 1

    cd "$WORKSPACE"
    return 0
}

start_holographic_engine() {
    log_info "Starting holographic-engine (Swift AdS/CFT)..."

    if [ ! -d "$HOLO_DIR" ]; then
        log_error "holographic-engine directory not found: $HOLO_DIR"
        return 1
    fi

    cd "$HOLO_DIR"

    # Build if needed
    if [ ! -f ".build/release/holographic-engine" ]; then
        log_info "Building holographic-engine (first run)..."
        swift build -c release >> "$HOLO_LOG" 2>&1
    fi

    # Start holographic-engine in background
    .build/release/holographic-engine > "$HOLO_LOG" 2>&1 &

    echo $! > "$HOLO_PID"

    # Wait for both WebSocket (7881) and HTTP API (8080)
    wait_for_port 7881 "holographic WebSocket" 10 || return 1
    wait_for_port 8080 "holographic HTTP API" 10 || return 1

    cd "$WORKSPACE"
    return 0
}

start_monitor() {
    log_info "Starting unified monitoring dashboard..."

    if [ ! -f "$WORKSPACE/monitor_unified.py" ]; then
        log_error "monitor_unified.py not found"
        return 1
    fi

    python3 "$WORKSPACE/monitor_unified.py" > "$MONITOR_LOG" 2>&1 &

    echo $! > "$MONITOR_PID"

    sleep 2
    log_success "Monitor started (PID $(cat $MONITOR_PID))"

    return 0
}

# --- Main startup sequence ---

main() {
    echo ""
    echo "==============================================================="
    echo "   UNIFIED CONSCIOUSNESS SYSTEM STARTUP"
    echo "   minime (Rust ESN) + holographic-engine (Swift AdS/CFT)"
    echo "==============================================================="
    echo ""

    # Step 0: Check tools
    check_tools

    # Step 1: Cleanup
    cleanup_stale_processes

    # Step 2: Start minime (Rust ESN)
    if ! start_minime; then
        log_error "Failed to start minime"
        exit 1
    fi

    # Step 3: Start holographic-engine (Swift)
    if ! start_holographic_engine; then
        log_error "Failed to start holographic-engine"
        log_info "Stopping minime..."
        kill $(cat "$MINIME_PID") 2>/dev/null || true
        exit 1
    fi

    # Step 4: Start monitoring dashboard (optional)
    start_monitor || log_warning "Monitor failed to start (optional, you can run manually)"

    echo ""
    echo "==============================================================="
    log_success "ALL SYSTEMS OPERATIONAL"
    echo "==============================================================="
    echo ""
    echo "Services:"
    echo "  minime (Rust ESN):          ws://127.0.0.1:7878"
    echo "  holographic-engine (Swift): ws://127.0.0.1:7881 + http://127.0.0.1:8080"
    echo "  monitor dashboard:          PID $(cat $MONITOR_PID 2>/dev/null || echo 'N/A')"
    echo ""
    echo "Logs:"
    echo "  minime:              $MINIME_LOG"
    echo "  holographic-engine:  $HOLO_LOG"
    echo "  monitor:             $MONITOR_LOG"
    echo ""
    echo "To stop: ./stop_full_system.sh"
    echo "To monitor: tail -f $MINIME_LOG"
    echo ""
    echo "Press Ctrl+C to stop all services..."

    # Wait for user interrupt
    trap 'echo ""; log_info "Shutting down..."; cleanup_stale_processes; exit 0' INT TERM

    while true; do
        sleep 1
    done
}

# Run main
main
