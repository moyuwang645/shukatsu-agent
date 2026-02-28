#!/bin/bash
# 就活Agent — Setup Script (Linux / macOS)
set -e

echo "🚀 就活Agent セットアップ"
echo "========================="

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 が見つかりません。先にインストールしてください。"
    exit 1
fi

PYTHON=python3

# Create venv
if [ ! -d "venv" ]; then
    echo "📦 仮想環境を作成中..."
    $PYTHON -m venv venv
fi

# Activate venv
source venv/bin/activate

# Install dependencies
echo "📦 依存パッケージをインストール中..."
pip install -r requirements.txt

# Install Playwright browser
echo "🌐 Playwright (Chromium) をインストール中..."
playwright install chromium

# Create data directory
mkdir -p data

# Copy .env if not exists
if [ ! -f ".env" ]; then
    echo "📄 .env.example → .env をコピー中..."
    cp .env.example .env
    echo "⚠️  .env を編集して API キーを設定してください。"
fi

echo ""
echo "✅ セットアップ完了！"
echo "   起動: ./start.sh"
echo "   または: source venv/bin/activate && python app.py"
