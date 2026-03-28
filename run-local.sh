#!/usr/bin/env bash
set -e

# KnowledgeKeeper — Local Development Runner
# Starts the mock API server and the frontend dev server together.
# Usage: ./run-local.sh
# Stop:  Ctrl-C (kills both processes)

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

cleanup() {
    echo ""
    echo "Shutting down..."
    kill $API_PID $FE_PID 2>/dev/null || true
    wait $API_PID $FE_PID 2>/dev/null || true
    echo "Done."
}
trap cleanup EXIT INT TERM

# --- Install Python deps if needed ---
echo "Checking Python dependencies..."
pip install -q flask flask-cors 2>/dev/null || pip install flask flask-cors

# --- Install frontend deps if needed ---
if [ ! -d "$ROOT_DIR/frontend/node_modules" ]; then
    echo "Installing frontend dependencies..."
    npm install --prefix "$ROOT_DIR/frontend"
fi

# --- Ensure .env.local exists ---
if [ ! -f "$ROOT_DIR/frontend/.env.local" ]; then
    cat > "$ROOT_DIR/frontend/.env.local" <<EOF
VITE_API_URL=/api
VITE_API_KEY=local-dev-key
VITE_USER_ID=local-dev-user
EOF
    echo "Created frontend/.env.local"
fi

# --- Start mock API server ---
echo ""
echo "Starting mock API server on http://localhost:8000 ..."
python "$ROOT_DIR/local_dev/server.py" &
API_PID=$!

# Give Flask a moment to bind
sleep 2

# --- Start frontend dev server ---
echo "Starting frontend dev server on http://localhost:5173 ..."
npm run dev --prefix "$ROOT_DIR/frontend" &
FE_PID=$!

echo ""
echo "========================================="
echo "  KnowledgeKeeper running locally"
echo "  Frontend:  http://localhost:5173"
echo "  Mock API:  http://localhost:8000"
echo "  Ctrl-C to stop both"
echo "========================================="
echo ""

# Wait for either process to exit
wait $API_PID $FE_PID
