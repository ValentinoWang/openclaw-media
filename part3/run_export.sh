#!/bin/bash
# Quick start script for cookie export

# Activate virtual environment
source .venv/bin/activate

# Run the export script
python3 auto_export_cookies.py "$@"
