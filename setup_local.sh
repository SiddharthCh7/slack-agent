#!/bin/bash
# OLake RAG - Local Development Setup Script
# 
# This script sets up the local Python 3.11 environment for development.
# Qdrant runs in Docker.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "======================================"
echo "  OLake RAG - Local Setup"
echo "======================================"

# Check Python version
PYTHON_BIN="/opt/homebrew/opt/python@3.11/libexec/bin/python3.11"
if [ ! -f "$PYTHON_BIN" ]; then
    echo "Error: Python 3.11 not found at $PYTHON_BIN"
    echo "Please install it with: brew install python@3.11"
    exit 1
fi

echo "✓ Python 3.11 found"

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    "$PYTHON_BIN" -m venv .venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment exists"
fi

# Activate virtual environment
source .venv/bin/activate

# Install/upgrade uv
echo "Checking uv..."
uv --version >/dev/null 2>&1 || pip install uv

# Sync dependencies
echo "Syncing dependencies..."
uv sync >/dev/null 2>&1

# Install RAG-specific dependencies
echo "Installing RAG dependencies..."
uv pip install -q qdrant-client sentence-transformers einops fastembed 2>/dev/null

echo "✓ Dependencies installed"

# Check Qdrant
echo ""
echo "Checking Qdrant..."
if curl -s http://localhost:6333/readyz >/dev/null 2>&1; then
    echo "✓ Qdrant is running"
else
    echo "⚠ Qdrant is not running"
    echo "  Start it with: docker-compose up -d"
fi

echo ""
echo "======================================"
echo "  Setup Complete!"
echo "======================================"
echo ""
echo "To activate the environment:"
echo "  source .venv/bin/activate"
echo ""
echo "To start Qdrant:"
echo "  docker-compose up -d"
echo ""
echo "To run ingestion:"
echo "  python services/rag/ingest_memory_efficient.py"
echo ""
echo "To run tests:"
echo "  PYTHONPATH=services/rag python -m tests.run_all"
echo ""
echo "To start RAG server:"
echo "  PYTHONPATH=services/rag python -m services.rag.server"
echo ""
