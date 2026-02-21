#!/bin/bash
#
# AI Auto-Trading System V2 Startup Script
#
# This script starts the trading system with proper environment setup.
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}AI Auto-Trading System V2${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Get project root (parent of scripts directory)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

cd "$PROJECT_ROOT"

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo -e "${RED}ERROR: .env file not found!${NC}"
    echo "Please copy .env.example to .env and configure your API keys."
    exit 1
fi

# Check if virtual environment exists
if [ -d ".venv" ]; then
    VENV_DIR=".venv"
elif [ -d "venv" ]; then
    VENV_DIR="venv"
else
    echo -e "${YELLOW}Virtual environment not found. Creating...${NC}"
    python3 -m venv .venv
    VENV_DIR=".venv"
fi

# Activate virtual environment
echo -e "${GREEN}Activating virtual environment...${NC}"
source "$VENV_DIR/bin/activate"

# Install/update dependencies
echo -e "${GREEN}Installing/updating dependencies...${NC}"
pip install -q --upgrade pip
pip install -q -r requirements.txt

# Check if Docker containers are running
echo -e "${GREEN}Checking Docker containers...${NC}"
if ! docker compose --profile dev ps | grep -q "Up"; then
    echo -e "${YELLOW}Docker containers not running. Starting...${NC}"
    docker compose --profile dev up -d
    echo -e "${GREEN}Waiting for services to be ready...${NC}"
    sleep 5
else
    echo -e "${GREEN}Docker containers are running.${NC}"
fi

# Run database migrations if needed
# TODO: Add migration command when available

# Start the trading system
echo ""
echo -e "${GREEN}Starting Trading System...${NC}"
echo -e "${YELLOW}Press Ctrl+C to stop gracefully${NC}"
echo ""

# CLAUDECODE 환경변수 제거 (중첩 세션 방지)
unset CLAUDECODE
unset CLAUDE_CODE

# Run with Python unbuffered output
PYTHONUNBUFFERED=1 python3 -m src.main

# Cleanup on exit
echo ""
echo -e "${GREEN}Trading System stopped.${NC}"
