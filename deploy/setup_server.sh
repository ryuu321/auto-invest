#!/bin/bash
# Oracle Cloud Ubuntu VM セットアップスクリプト
# 実行: bash setup_server.sh

set -e
echo "=== AI Holdings 投資ボット サーバーセットアップ ==="

# 1. システム更新 + Python
echo "[1/5] パッケージ更新..."
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv git

# 2. プロジェクトディレクトリ
PROJECT_DIR="$HOME/auto-invest"
echo "[2/5] プロジェクトディレクトリ: $PROJECT_DIR"
mkdir -p "$PROJECT_DIR/data"

# 3. Python 仮想環境 + 依存パッケージ
echo "[3/5] Python環境構築..."
python3 -m venv "$PROJECT_DIR/venv"
source "$PROJECT_DIR/venv/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet yfinance flask requests pandas numpy feedparser
echo "インストール完了"

# 4. systemd サービス登録（ボット3本 + ダッシュボード）
echo "[4/5] systemdサービス登録..."

create_service() {
  local name=$1
  local script=$2
  sudo tee /etc/systemd/system/${name}.service > /dev/null <<EOF
[Unit]
Description=AI Holdings ${name}
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=${PROJECT_DIR}
Environment=PYTHONIOENCODING=utf-8
ExecStart=${PROJECT_DIR}/venv/bin/python -u ${script}
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF
}

create_service "bot-short"     "short/main.py"
create_service "bot-medium"    "medium/main.py"
create_service "bot-long"      "long/main.py"
create_service "bot-dashboard" "dashboard/app.py"

sudo systemctl daemon-reload
sudo systemctl enable bot-short bot-medium bot-long bot-dashboard
echo "サービス登録完了"

# 5. ファイアウォール開放（ダッシュボード用）
echo "[5/5] ポート5000開放..."
sudo iptables -I INPUT -p tcp --dport 5000 -j ACCEPT
sudo netfilter-persistent save 2>/dev/null || true

echo ""
echo "=== セットアップ完了 ==="
echo "次のステップ: コードをアップロードしてから以下を実行"
echo "  sudo systemctl start bot-short bot-medium bot-long bot-dashboard"
echo "  sudo systemctl status bot-dashboard"
