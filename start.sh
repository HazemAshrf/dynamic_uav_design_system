#!/bin/bash

# Dynamic Agent Dashboard - Quick Start Script
# Simple bash wrapper for the Python system runner

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
cd "$PROJECT_DIR"

echo "🚀 Dynamic Agent Dashboard - Quick Start"
echo "========================================"

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "❌ Error: UV package manager not found"
    echo "Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Add uv to PATH if needed
export PATH="$HOME/.local/bin:$PATH"

# Check Python version
python_version=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
required_version="3.11"

if [ "$(printf '%s\n' "$required_version" "$python_version" | sort -V | head -n1)" != "$required_version" ]; then
    echo "❌ Error: Python 3.11+ required, found $python_version"
    exit 1
fi

echo "✅ Environment checks passed"
echo ""

# Parse command line arguments
INIT_DB=true
OPEN_BROWSER=true
TEST_ONLY=false
STATUS_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --no-init-db)
            INIT_DB=false
            shift
            ;;
        --no-browser)
            OPEN_BROWSER=false
            shift
            ;;
        --test-only)
            TEST_ONLY=true
            shift
            ;;
        --status-only)
            STATUS_ONLY=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --no-init-db     Skip database initialization"
            echo "  --no-browser     Don't open browser automatically" 
            echo "  --test-only      Run system tests only"
            echo "  --status-only    Show system status only"
            echo "  --help, -h       Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                    # Start full system"
            echo "  $0 --test-only       # Run tests"
            echo "  $0 --status-only     # Check status"
            echo "  $0 --no-browser      # Start without opening browser"
            exit 0
            ;;
        *)
            echo "❌ Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Build Python command
CMD="uv run python run_system.py"

if [ "$INIT_DB" = false ]; then
    CMD="$CMD --no-init-db"
fi

if [ "$OPEN_BROWSER" = false ]; then
    CMD="$CMD --no-browser"
fi

if [ "$TEST_ONLY" = true ]; then
    CMD="$CMD --test-only"
fi

if [ "$STATUS_ONLY" = true ]; then
    CMD="$CMD --status-only"
fi

# Setup cleanup trap
cleanup() {
    echo ""
    echo "🛑 Shutting down system..."
    # Kill any remaining processes
    pkill -f "uvicorn backend.main:app" 2>/dev/null || true
    pkill -f "streamlit run frontend/main.py" 2>/dev/null || true
    echo "✅ Cleanup complete"
}

trap cleanup EXIT INT TERM

# Run the system
echo "🎯 Starting Dynamic Agent Dashboard..."
echo "Command: $CMD"
echo ""

exec $CMD