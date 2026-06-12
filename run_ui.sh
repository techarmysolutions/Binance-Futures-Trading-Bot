#!/usr/bin/env bash
# Launch the browser dashboard. Open http://localhost:8000 after it starts.
set -e
pip install -r requirements.txt
echo ""
echo "  Dashboard starting at http://localhost:8000"
echo ""
uvicorn server:app --host 0.0.0.0 --port 8000
