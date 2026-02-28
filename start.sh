#!/bin/bash
# 就活Agent — Start Script (Linux / macOS)
set -e

cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "❌ venv が見つかりません。先に ./setup.sh を実行してください。"
    exit 1
fi

source venv/bin/activate

# Create data directory if missing
mkdir -p data

echo "🚀 就活Agent を起動中..."
echo "   Dashboard: http://localhost:5000"
echo ""

python app.py
